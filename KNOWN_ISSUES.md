# KNOWN_ISSUES

## Hanging Tests
- `archon/tests/test_api_http_auth.py` hangs during execution and is excluded from routine runs.
- `archon/tests/test_auth.py` hangs during execution and is excluded from routine runs.
- `archon/tests/test_billing_integration.py` hangs during execution and is excluded from routine runs.
- `archon/tests/test_deploy_worker.py` hangs during execution and is excluded from routine runs.

## Failing Tests
- `tests/test_api_server.py` fails during collection with `PydanticUndefinedAnnotation` (`TaskRequest` not defined).
- Pre-existing issue, not introduced by cleanup.
