-- Run after applying the migration in the Supabase SQL Editor.
-- This is a rolled-back smoke test: it requires one existing participant,
-- exercises English Session 1 assignment and resume, and persists no changes.
begin;

do $$
declare
  test_participant_id uuid;
  test_prompts jsonb;
  first_result jsonb;
  resumed_result jsonb;
  first_count bigint;
  resumed_count bigint;
begin
  select p.participant_id
  into test_participant_id
  from public.participants as p
  order by p.created_at
  limit 1;

  if test_participant_id is null then
    raise exception 'Regression test requires at least one participant row';
  end if;

  select jsonb_agg(
    jsonb_build_object(
      'utterance_number', generated.prompt_number,
      'sentence_id', 'MIGRATION_TEST_' || lpad(generated.prompt_number::text, 2, '0'),
      'sentence_text', 'Migration regression prompt ' || generated.prompt_number
    ) order by generated.prompt_number
  )
  into test_prompts
  from generate_series(1, 10) as generated(prompt_number);

  select count(*), jsonb_agg(to_jsonb(assigned) order by assigned.utterance_number)
  into first_count, first_result
  from public.assign_session_prompts(
    test_participant_id,
    'english',
    1::smallint,
    test_prompts
  ) as assigned;

  select count(*), jsonb_agg(to_jsonb(assigned) order by assigned.utterance_number)
  into resumed_count, resumed_result
  from public.assign_session_prompts(
    test_participant_id,
    'english',
    1::smallint,
    test_prompts
  ) as assigned;

  if first_count <> 10 or resumed_count <> 10 then
    raise exception 'Expected ten rows on assignment and resume; got % and %', first_count, resumed_count;
  end if;
  if first_result is distinct from resumed_result then
    raise exception 'Session 1 result changed when resumed';
  end if;
end;
$$;

rollback;
