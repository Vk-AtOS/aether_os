# PipelineRun: splitting `FactoryPipeline._execute_pipeline` (KAN-57)

## Problem
`_execute_pipeline` was one ~700 line method with a 30 argument signature and about a
dozen shared locals (`accumulated_context`, `results`, `phases_to_run`, `project_dir`,
`_bridge`, `pipeline_start`, ...). A mechanical split was impossible because every
piece reads or writes those locals, so `orchestrator/factory_pipeline.py` stayed at
1202 lines on the exception list.

## Design
* `orchestrator/pipeline_run.py` holds the `PipelineRun` dataclass: the request
  (the 30 arguments), the runtime state (the former locals) and `fp`, the
  `factory_pipeline` module itself.
* Steps are plain async functions that take the run and return either `None`
  (carry on) or a terminal result dict (the run ended: aborted, cancelled).
  They mutate the run in place, exactly as the locals were mutated.
* Setup (`pipeline_run.py`): `prepare` = create the project dir, DB row, council
  preflight, org settings, context (`build_context`), learning, phase selection,
  stage toggles, monitor bridge, DAG waves.
* Execution (`pipeline_steps.py`): `run_wave` (parallel wave), `run_phase` (single
  phase: skip check, timeout, gate block, guided pause, post-processing, error
  handlers), `check_control` (cancel / pause), `finish` (completion events and
  background tasks), and `execute` which loops the waves.
* Guided questionnaire pause moved verbatim to `pipeline_questionnaire.py`.
* `factory_pipeline.py` keeps `FactoryPipeline` (`run`, `_run_phase`, `_abort_run`,
  `_update_state`, `run_change_request`, thin `_execute_pipeline`), `get_factory`, and
  re-exports every old module level name.

## Patch points (behaviour preservation)
Tests and tooling monkeypatch names on `aether_os.orchestrator.factory_pipeline`
(`emit`, `get_control`, `_load_supervisor`, `delivery_council_check`, ...). Moved code
therefore reads every such collaborator as `run.fp.<name>` at call time, not through its
own import, so a patch on the old module still takes effect. The `continue` that skipped
the control check for a skipped s04 is kept as the `SKIPPED` sentinel returned by `run_phase`.

## Verification
The whole existing suite around the pipeline (gate blocking, integration, e2e smoke,
timeout, admission, multi tenancy) runs unchanged against the new layout.
