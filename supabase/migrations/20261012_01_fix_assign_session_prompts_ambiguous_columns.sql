-- Fix output-variable ambiguity in assign_session_prompts without changing its
-- signature, return type, privileges, data, or prompt/session behavior.
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

  select p.* into person
  from public.participants as p
  where p.participant_id = p_participant_id;
  if person.participant_id is null then raise exception 'Participant not found'; end if;

  insert into public.sessions(participant_id, speaker_id, language, session_number)
  values (person.participant_id, person.speaker_id, p_language, p_session_number)
  on conflict (participant_id, language, session_number) do nothing;

  select s.* into current_session
  from public.sessions as s
  where s.participant_id = p_participant_id
    and s.language = p_language
    and s.session_number = p_session_number;

  if p_session_number = 1 then
    for prompt in
      select incoming.value
      from jsonb_array_elements(p_prompts) as incoming(value)
    loop
      prompt_index := prompt_index + 1;
      insert into public.common_prompts(language, prompt_number, sentence_id, sentence_text)
      values (p_language, prompt_index, prompt->>'sentence_id', prompt->>'sentence_text')
      on conflict (language, prompt_number) do nothing;
    end loop;

    select jsonb_agg(
      jsonb_build_object(
        'sentence_id', cp.sentence_id,
        'sentence_text', cp.sentence_text
      ) order by cp.prompt_number
    )
    into prompt_set
    from public.common_prompts as cp
    where cp.language = p_language;
  else
    prompt_set := p_prompts;
  end if;

  if coalesce(jsonb_array_length(prompt_set), 0) <> 10 then
    raise exception 'Canonical script must contain ten prompts';
  end if;

  prompt_index := 0;
  for prompt in
    select assigned.value
    from jsonb_array_elements(prompt_set) as assigned(value)
  loop
    prompt_index := prompt_index + 1;
    insert into public.utterances(session_id, participant_id, speaker_id, language, session_number, utterance_number, sentence_id, sentence_text)
    values (current_session.session_id, person.participant_id, person.speaker_id, p_language, p_session_number, prompt_index,
      prompt->>'sentence_id', prompt->>'sentence_text')
    on conflict (participant_id, language, session_number, utterance_number) do nothing;
  end loop;

  return query
  select u.utterance_number, u.sentence_id, u.sentence_text,
         u.status, u.storage_path, u.duration_seconds
  from public.utterances as u
  where u.participant_id = p_participant_id
    and u.language = p_language
    and u.session_number = p_session_number
  order by u.utterance_number;
end;
$$;
