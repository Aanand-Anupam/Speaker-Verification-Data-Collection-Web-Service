-- Run this once in the Supabase SQL Editor for a new project.
create extension if not exists pgcrypto;
create sequence if not exists public.speaker_id_seq start with 1;

create table if not exists public.participants (
  participant_id uuid primary key default gen_random_uuid(),
  roll_number text not null,
  roll_number_normalized text not null unique,
  name text not null,
  speaker_id text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists public.sessions (
  session_id uuid primary key default gen_random_uuid(),
  participant_id uuid not null references public.participants(participant_id),
  speaker_id text not null,
  language text not null check (language in ('english','hindi','telugu','khasi')),
  session_number smallint not null check (session_number in (1,2)),
  created_at timestamptz not null default now(),
  unique (participant_id, language, session_number)
);

-- The first accepted Session 1 script becomes the canonical language script.
-- Subsequent participants reuse these exact ten prompts even if source files change.
create table if not exists public.common_prompts (
  language text not null check (language in ('english','hindi','telugu','khasi')),
  prompt_number smallint not null check (prompt_number between 1 and 10),
  sentence_id text not null,
  sentence_text text not null,
  primary key (language, prompt_number),
  unique (language, sentence_id)
);

create table if not exists public.utterances (
  utterance_id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions(session_id),
  participant_id uuid not null references public.participants(participant_id),
  speaker_id text not null,
  language text not null check (language in ('english','hindi','telugu','khasi')),
  session_number smallint not null check (session_number in (1,2)),
  utterance_number smallint not null check (utterance_number between 1 and 10),
  sentence_id text not null,
  sentence_text text not null,
  status text not null default 'missing' check (status in ('missing','completed')),
  storage_path text,
  duration_seconds real,
  created_at timestamptz not null default now(),
  unique (participant_id, language, session_number, utterance_number),
  unique (speaker_id, language, session_number, utterance_number)
);

alter table public.participants enable row level security;
alter table public.sessions enable row level security;
alter table public.utterances enable row level security;
alter table public.common_prompts enable row level security;
revoke all on public.participants, public.sessions, public.utterances, public.common_prompts from anon, authenticated;
revoke all on sequence public.speaker_id_seq from public, anon, authenticated;

create or replace function public.register_participant(p_name text, p_roll_number text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  normalized text;
  created public.participants%rowtype;
  existing public.participants%rowtype;
begin
  if p_name is null or length(btrim(p_name)) not between 1 and 200 then
    raise exception 'Name must contain 1 to 200 characters';
  end if;
  if p_roll_number is null or length(btrim(p_roll_number)) not between 1 and 64 then
    raise exception 'Roll number must contain 1 to 64 characters';
  end if;
  normalized := lower(regexp_replace(btrim(p_roll_number), '\s+', ' ', 'g'));
  insert into public.participants(roll_number, roll_number_normalized, name, speaker_id)
  values (btrim(p_roll_number), normalized, btrim(p_name), 'S' || lpad(nextval('public.speaker_id_seq')::text, 3, '0'))
  on conflict (roll_number_normalized) do nothing
  returning * into created;
  if created.participant_id is not null then
    return jsonb_build_object('participant_id', created.participant_id, 'speaker_id', created.speaker_id, 'is_returning', false);
  end if;
  update public.participants set name = btrim(p_name), roll_number = btrim(p_roll_number)
  where roll_number_normalized = normalized returning * into existing;
  return jsonb_build_object('participant_id', existing.participant_id, 'speaker_id', existing.speaker_id, 'is_returning', true);
end;
$$;

-- Optional migration for participants registered by the earlier local recorder.
create or replace function public.import_local_participant(p_name text, p_roll_number text, p_speaker_id text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  normalized text;
  existing public.participants%rowtype;
  imported public.participants%rowtype;
  sid_number bigint;
begin
  if p_speaker_id !~ '^S[0-9]{3,}$' then raise exception 'Invalid existing speaker ID'; end if;
  normalized := lower(regexp_replace(btrim(p_roll_number), '\s+', ' ', 'g'));
  select * into existing from public.participants where roll_number_normalized = normalized;
  if existing.participant_id is not null then
    if existing.speaker_id <> p_speaker_id then raise exception 'Roll number is already mapped to a different speaker ID'; end if;
    return jsonb_build_object('participant_id', existing.participant_id, 'speaker_id', existing.speaker_id, 'is_returning', true);
  end if;
  insert into public.participants(roll_number, roll_number_normalized, name, speaker_id)
  values (btrim(p_roll_number), normalized, btrim(p_name), p_speaker_id)
  returning * into imported;
  sid_number := substring(p_speaker_id from 2)::bigint;
  if sid_number >= (select last_value from public.speaker_id_seq) then perform setval('public.speaker_id_seq', sid_number, true); end if;
  return jsonb_build_object('participant_id', imported.participant_id, 'speaker_id', imported.speaker_id, 'is_returning', false);
end;
$$;

create or replace function public.advance_speaker_id_sequence(p_minimum bigint)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if p_minimum >= (select last_value from public.speaker_id_seq) then
    perform setval('public.speaker_id_seq', p_minimum, true);
  end if;
end;
$$;

create or replace function public.assign_session_prompts(
  p_participant_id uuid,
  p_language text,
  p_session_number smallint,
  p_prompts jsonb
)
returns table(utterance_number smallint, sentence_id text, sentence_text text, status text, storage_path text, duration_seconds real)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  person public.participants%rowtype;
  current_session public.sessions%rowtype;
  prompt jsonb;
  prompt_set jsonb;
  prompt_index smallint := 0;
begin
  if p_language not in ('english','hindi','telugu','khasi') or p_session_number not in (1,2) then
    raise exception 'Unsupported language or session';
  end if;
  if jsonb_typeof(p_prompts) <> 'array' or jsonb_array_length(p_prompts) <> 10 then
    raise exception 'Exactly ten prompts are required';
  end if;
  select * into person from public.participants where participant_id = p_participant_id;
  if person.participant_id is null then raise exception 'Participant not found'; end if;
  insert into public.sessions(participant_id, speaker_id, language, session_number)
  values (person.participant_id, person.speaker_id, p_language, p_session_number)
  on conflict (participant_id, language, session_number) do nothing;
  select * into current_session from public.sessions
  where participant_id = p_participant_id and language = p_language and session_number = p_session_number;
  if p_session_number = 1 then
    for prompt in select value from jsonb_array_elements(p_prompts) loop
      prompt_index := prompt_index + 1;
      insert into public.common_prompts(language, prompt_number, sentence_id, sentence_text)
      values (p_language, prompt_index, prompt->>'sentence_id', prompt->>'sentence_text')
      on conflict (language, prompt_number) do nothing;
    end loop;
    select jsonb_agg(jsonb_build_object('sentence_id', sentence_id, 'sentence_text', sentence_text) order by prompt_number)
    into prompt_set from public.common_prompts where language = p_language;
  else
    prompt_set := p_prompts;
  end if;
  if coalesce(jsonb_array_length(prompt_set), 0) <> 10 then raise exception 'Canonical script must contain ten prompts'; end if;
  prompt_index := 0;
  for prompt in select value from jsonb_array_elements(prompt_set) loop
    prompt_index := prompt_index + 1;
    insert into public.utterances(session_id, participant_id, speaker_id, language, session_number, utterance_number, sentence_id, sentence_text)
    values (current_session.session_id, person.participant_id, person.speaker_id, p_language, p_session_number, prompt_index,
      prompt->>'sentence_id', prompt->>'sentence_text')
    on conflict (participant_id, language, session_number, utterance_number) do nothing;
  end loop;
  return query select u.utterance_number, u.sentence_id, u.sentence_text, u.status, u.storage_path, u.duration_seconds
  from public.utterances u where u.participant_id = p_participant_id and u.language = p_language and u.session_number = p_session_number
  order by u.utterance_number;
end;
$$;

revoke all on function public.register_participant(text,text) from public, anon, authenticated;
revoke all on function public.import_local_participant(text,text,text) from public, anon, authenticated;
revoke all on function public.advance_speaker_id_sequence(bigint) from public, anon, authenticated;
revoke all on function public.assign_session_prompts(uuid,text,smallint,jsonb) from public, anon, authenticated;
grant execute on function public.register_participant(text,text) to service_role;
grant execute on function public.import_local_participant(text,text,text) to service_role;
grant execute on function public.advance_speaker_id_sequence(bigint) to service_role;
grant execute on function public.assign_session_prompts(uuid,text,smallint,jsonb) to service_role;

insert into storage.buckets(id, name, public)
values ('speaker-audio', 'speaker-audio', false)
on conflict (id) do update set public = false;
-- Do not add anon/authenticated storage policies. The backend service role is the only client.
