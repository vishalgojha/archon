DRAWER_COPY = {
    "core": {
        "title": "Core Control",
        "icon": "[C]",
        "tagline": "Bring ARCHON up, check status, and enter chat.",
        "availability": "live",
        "explanation": (
            "Core commands cover first-run setup, config validation, runtime status, "
            "and the interactive chat path that feeds the orchestrator without leaving "
            "the terminal."
        ),
        "requires": ["config.archon.yaml", "provider keys in environment"],
        "commands": {
            "core.init": "Create config, test providers, check Ollama, and set budgets.",
            "core.validate": "Validate config schema and ping configured providers live.",
            "core.status": "Read config and worker queue state from the active runtime.",
            "core.chat": "Launch the ARCHON chat and TUI experience.",
            "core.studio": "Print Studio launch steps or run the dev server.",
        },
    },
    "agents": {
        "title": "Agent Sessions",
        "icon": "[A]",
        "tagline": "Run tasks, local debate runs, and terminal sessions.",
        "availability": "live",
        "explanation": (
            "Agent session commands expose the orchestration entry points: a single task "
            "call against the API, a local debate run, and the full interactive terminal "
            "session."
        ),
        "requires": ["validated config", "BYOK or Ollama access"],
        "commands": {
            "agents.task": "Send one goal through the API task surface.",
            "agents.debate": "Run a local orchestration pass without HTTP.",
            "agents.tui": "Open the interactive terminal session for ARCHON.",
        },
    },
    "memory": {
        "title": "Memory Stack",
        "icon": "[M]",
        "tagline": "Search stored context and manage memory exports.",
        "availability": "partial",
        "explanation": (
            "Memory commands expose the tenant-safe store behind ARCHON recalls, letting "
            "operators search persisted context and move memory in or out when needed."
        ),
        "requires": ["memory database", "tenant identifier for scoped reads"],
        "commands": {
            "memory.search": "Query memory by tenant and ranked similarity.",
            "memory.export": "Export a tenant memory namespace for audit or transfer.",
            "memory.import": "Import a tenant memory namespace from a prior export.",
        },
    },
    "evolve": {
        "title": "Evolution Engine",
        "icon": "[E]",
        "tagline": "Stage candidates, compare results, and promote winners.",
        "availability": "live",
        "explanation": (
            "The evolution stack handles staging, audit trails, and controlled workflow "
            "promotion. Use plan to stage candidates and apply to promote with human "
            "approval."
        ),
        "requires": ["workflow JSON file", "audit trail storage"],
        "commands": {
            "evolve.plan": "Stage an evolution candidate and preview the experiment.",
            "evolve.apply": "Promote an approved evolution result into the workflow file.",
        },
    },
    "skills": {
        "title": "Skill Studio",
        "icon": "[S]",
        "tagline": "Propose, test, and promote skill definitions.",
        "availability": "live",
        "explanation": (
            "Skill commands analyze execution gaps, stage new skill YAML definitions, "
            "run A/B trials, and promote approved skills into active routing."
        ),
        "requires": ["audit trail database", "skills registry directory"],
        "commands": {
            "skills.list": "Show all registered skill definitions.",
            "skills.propose": "Analyze gaps and stage a new skill definition.",
            "skills.apply": "Run A/B trials and promote a staged skill.",
        },
    },
    "providers": {
        "title": "Providers",
        "icon": "[P]",
        "tagline": "Inspect BYOK routing and test provider health.",
        "availability": "live",
        "explanation": (
            "Provider commands read the active config and environment so operators can "
            "see role assignments, confirm which providers are wired, and run live "
            "health probes with measured latency."
        ),
        "requires": ["config.archon.yaml", "provider keys in environment"],
        "commands": {
            "providers.list": "Show the configured provider assigned to each role.",
            "providers.test": "Run live provider health checks and latency probes.",
        },
    },
    "ops": {
        "title": "Operations",
        "icon": "[O]",
        "tagline": "Serve APIs, check health, and manage background workers.",
        "availability": "live",
        "explanation": (
            "Operations commands cover the API server, health checks, and the "
            "SQLite-backed deployment worker that drains queued tasks from the "
            "runtime directory."
        ),
        "requires": ["runtime directory", "worker queue database when enabled"],
        "commands": {
            "ops.serve": "Start the ARCHON API server.",
            "ops.health": "Check API health from the CLI.",
            "ops.worker": "Start the deployment worker and stream its logs.",
            "ops.worker-status": "Read worker queue counts from the runtime database.",
        },
    },
    "redteam": {
        "title": "Red-Team",
        "icon": "[R]",
        "tagline": "Run regression scans and export red-team reports.",
        "availability": "live",
        "explanation": (
            "Red-team commands generate regression artifacts that summarize adversarial "
            "coverage by attack vector and capture any detected regressions."
        ),
        "requires": ["output directory"],
        "commands": {
            "redteam.regression": "Run the automated red-team regression scan.",
        },
    },
}


COMMAND_COPY = {
    "core.init": {
        "what": "Initialize ARCHON by selecting providers, checking Ollama, setting budgets, and writing the first runtime config.",
        "steps": [
            "Select the primary provider and validate the supplied key.",
            "Choose the fast-agent provider for cheap routing paths.",
            "Check Ollama reachability and pull the required model when missing.",
            "Capture the budget limit and write config.archon.yaml.",
            "Run validation against the completed config.",
        ],
        "results": {
            "success": "ARCHON is ready. Primary provider: {primary_provider}. Fast provider: {fast_provider}. Daily budget: {budget_limit}. Validation: {validation_status}.",
        },
        "next_steps": [
            "Run archon core status to verify runtime state.",
            "Run archon ops serve to start the API.",
            "Run archon core chat to enter the terminal session.",
        ],
    },
    "core.validate": {
        "what": "Validate the active config file and run live provider health probes for every configured provider.",
        "steps": [
            "Load config.archon.yaml and normalize provider settings.",
            "Validate schema and budget policy.",
            "Ping each configured provider and capture status plus latency.",
            "Summarize failures, warnings, and passing providers.",
        ],
        "results": {
            "success": "Validation finished with status {status}. Providers checked: {provider_count}. Failures: {failure_count}.",
            "failure": "Validation finished with status {status}. Providers checked: {provider_count}. Failures: {failure_count}.",
        },
        "next_steps": [
            "Fix any failed provider checks before going live.",
            "Run archon providers list to inspect role assignments.",
            "Run archon providers test to recheck network latency.",
        ],
    },
    "core.status": {
        "what": "Read runtime status for configured providers and the worker queue.",
        "steps": [
            "Load config.archon.yaml.",
            "Resolve the runtime directory and worker queue database.",
            "Summarize pending, running, completed, and failed tasks.",
        ],
        "results": {
            "success": "Status reported. Queue pending={pending} running={running} completed={completed} failed={failed}.",
        },
        "next_steps": [
            "Run archon ops health to confirm the API is reachable.",
            "Run archon agents task to send a live prompt.",
        ],
    },
    "core.chat": {
        "what": "Open the agentic terminal UI and start a live orchestration session.",
        "steps": [
            "Load config or onboarding defaults.",
            "Enter the agentic TUI.",
        ],
        "results": {
            "success": "Chat session closed.",
        },
        "next_steps": [
            "Run archon agents task for a single API call.",
            "Run archon core status to review runtime health.",
        ],
    },
    "core.studio": {
        "what": "Open Archon Studio or print the steps to launch the UI.",
        "steps": [
            "Resolve the Studio workspace path.",
            "Prepare the API base and dev server target.",
            "Request approval if launching the dev server.",
        ],
        "results": {
            "success": "Studio details ready. Path {path}. Dev URL {dev_url}.",
            "denied": "Studio launch cancelled by approval gate.",
        },
        "next_steps": [
            "Run archon ops serve to start the API.",
            "Use archon core studio --dev to run the UI.",
        ],
    },
    "agents.task": {
        "what": "Send a goal to the running ARCHON API and return the final response.",
        "steps": [
            "Normalize the target API base URL.",
            "Build the task payload and authorization headers.",
            "Call the API and return the response payload.",
        ],
        "results": {
            "success": "Task finished with confidence {confidence}% and spent {spent_usd}.",
        },
        "next_steps": [
            "Run archon agents debate to compare local output.",
            "Run archon core status for runtime status.",
        ],
    },
    "agents.debate": {
        "what": "Run a local debate pass without calling the HTTP API.",
        "steps": [
            "Load config and initialize the orchestrator.",
            "Run debate mode locally and stream live events.",
            "Return the final synthesis output.",
        ],
        "results": {
            "success": "Debate completed with confidence {confidence}% and spent {spent_usd}.",
        },
        "next_steps": [
            "Run archon agents task to compare API output.",
            "Run archon core chat for a live session.",
        ],
    },
    "agents.tui": {
        "what": "Launch the interactive ARCHON terminal session.",
        "steps": [
            "Load config and resolve budget overrides.",
            "Open the agentic TUI session.",
        ],
        "results": {
            "success": "TUI session closed.",
        },
        "next_steps": [
            "Run archon agents task for a single API call.",
            "Run archon core status for runtime status.",
        ],
    },
    "skills.list": {
        "what": "List all registered skills and their routing status.",
        "steps": [
            "Resolve the config path.",
            "Load skills from the registry.",
            "Render the registry list.",
        ],
        "results": {
            "success": "Loaded {count} skill(s).",
        },
        "next_steps": [
            "Run archon skills propose to stage a new skill.",
            "Run archon skills apply <name> to promote a staged skill.",
        ],
    },
    "skills.propose": {
        "what": "Analyze recent gaps and stage a new skill proposal.",
        "steps": [
            "Load config and initialize the skill creator.",
            "Analyze failed or low-confidence tasks for gaps.",
            "Request approval and write the staged skill definition.",
        ],
        "results": {
            "success": "Staged skill {skill}.",
            "empty": "No gaps found for proposal.",
            "denied": "Skill proposal denied.",
        },
        "next_steps": [
            "Run archon skills apply <name> to test the staged skill.",
            "Run archon skills list to review registry status.",
        ],
    },
    "skills.apply": {
        "what": "Run A/B testing for a staged skill and promote on success.",
        "steps": [
            "Load config and initialize the skill creator.",
            "Run A/B tests and request approval for promotion.",
        ],
        "results": {
            "success": "Skill {skill} promoted with success rate {success_rate}.",
            "rejected": "Skill {skill} did not meet the promotion threshold.",
            "denied": "Skill promotion denied.",
        },
        "next_steps": [
            "Run archon skills list to confirm the active skill status.",
        ],
    },
    "memory.search": {
        "what": "Search the tenant memory store by similarity.",
        "steps": [
            "Load config and initialize the memory store.",
            "Search for the query within the tenant namespace.",
            "Render the top results.",
        ],
        "results": {
            "success": "Found {result_count} result(s) for tenant {tenant_id}.",
            "empty": "No memory results for tenant {tenant_id}.",
        },
        "next_steps": [
            "Run archon memory export to back up stored context.",
            "Run archon agents task to generate new memory entries.",
        ],
    },
    "memory.export": {
        "what": "Export a tenant memory namespace to a JSONL file.",
        "steps": [
            "Load config and initialize the memory store.",
            "Write the export file to disk.",
            "Report rows exported.",
        ],
        "results": {
            "success": "Exported {row_count} memory entries to {output_path}.",
        },
        "next_steps": [
            "Store the export in a secure archive.",
            "Use archon memory import to restore into a new tenant.",
        ],
    },
    "memory.import": {
        "what": "Import a tenant memory namespace from a JSONL export.",
        "steps": [
            "Load config and initialize the memory store.",
            "Read the import file and apply changes.",
            "Summarize imported, replaced, and skipped records.",
        ],
        "results": {
            "success": "Imported {imported} entries (replaced={replaced}, skipped={skipped}).",
        },
        "next_steps": [
            "Run archon memory search to verify the import.",
            "Run archon agents task to build on the imported context.",
        ],
    },
    "evolve.plan": {
        "what": "Stage an evolution candidate from a workflow JSON file.",
        "steps": [
            "Load the workflow JSON file.",
            "Run debate optimization to propose a candidate.",
            "Stage the candidate in the audit trail.",
        ],
        "results": {
            "success": "Staged candidate version {candidate_version} for workflow {workflow_id}.",
        },
        "next_steps": [
            "Review the staged candidate JSON output.",
            "Run archon evolve apply to promote the candidate.",
        ],
    },
    "evolve.apply": {
        "what": "Promote a staged evolution candidate into the workflow file.",
        "steps": [
            "Load the workflow file and staged candidate.",
            "Request approval for the file write.",
            "Write the promoted workflow to disk.",
        ],
        "results": {
            "success": "Promoted workflow to version {to_version}.",
            "denied": "Promotion denied. Workflow remains at version {restored_version}.",
        },
        "next_steps": [
            "Run archon evolve plan to stage another candidate.",
            "Run archon core chat to validate outputs manually.",
        ],
    },
    "providers.list": {
        "what": "List BYOK provider role assignments and key status.",
        "steps": [
            "Load config and resolve provider roles.",
            "Check environment keys for each provider.",
            "Render the role-to-provider table.",
        ],
        "results": {
            "success": "Reported {provider_count} provider role assignments.",
        },
        "next_steps": [
            "Run archon providers test to verify connectivity.",
            "Run archon core validate after updating keys.",
        ],
    },
    "providers.test": {
        "what": "Run live provider health checks and measure latency.",
        "steps": [
            "Load config and list configured providers.",
            "Run provider checks with a timeout.",
            "Render pass/fail status with latency.",
        ],
        "results": {
            "success": "Checked {provider_count} providers; {pass_count} passed.",
        },
        "next_steps": [
            "Fix failed keys and rerun providers test.",
            "Run archon agents task to confirm outputs.",
        ],
    },
    "ops.serve": {
        "what": "Start the ARCHON API server from the CLI.",
        "steps": [
            "Ensure a config file exists, onboarding if needed.",
            "Load environment variables and config.",
            "Start the API server.",
        ],
        "results": {
            "success": "ARCHON API server started on {host}:{port}.",
        },
        "next_steps": [
            "Run archon ops health to verify the server.",
            "Run archon agents task once the server is live.",
        ],
    },
    "ops.health": {
        "what": "Check the health endpoint for the running ARCHON API and summarize the response.",
        "steps": [
            "Request the API health endpoint.",
            "Render server status, version, git SHA, and uptime.",
        ],
        "results": {
            "success": "Server status is {status}. Version: {version}.",
        },
        "next_steps": [
            "Run archon ops serve if the server is down.",
            "Run archon core status for runtime detail.",
        ],
    },
    "ops.worker": {
        "what": "Start the deployment worker in a subprocess and stream log lines from the active runtime.",
        "steps": [
            "Resolve the runtime directory and worker database path.",
            "Start archon.deploy.worker in a subprocess.",
            "Stream worker stdout and stderr to the terminal.",
        ],
        "results": {
            "success": "Worker exited with code {return_code}.",
        },
        "next_steps": [
            "Run archon ops worker-status to inspect queue progress.",
            "Run archon core status for runtime summary.",
        ],
    },
    "ops.worker-status": {
        "what": "Read the worker queue database and summarize pending, running, completed, and failed tasks.",
        "steps": [
            "Resolve the runtime directory and queue database path.",
            "Read task counts from the SQLite worker queue.",
            "Render the queue summary for operators.",
        ],
        "results": {
            "success": "Queue pending={pending} running={running} completed={completed} failed={failed}.",
        },
        "next_steps": [
            "Run archon ops worker to start or restart the worker.",
            "Run archon core status for the broader runtime summary.",
        ],
    },
    "redteam.regression": {
        "what": "Generate a red-team regression report for the current build.",
        "steps": [
            "Resolve the output directory for red-team artifacts.",
            "Request approval to write the regression report.",
            "Write regression report files to disk.",
        ],
        "results": {
            "success": "Red-team regression scan complete. Scan id {scan_id}.",
        },
        "next_steps": [
            "Review the generated markdown report.",
            "Archive the JSON output for comparisons.",
        ],
    },
}


FLOW_COPY = {
    "init": {
        "title": "ARCHON Setup",
        "intro": "Configure ARCHON for real execution by wiring providers, validating local models, and setting an operator budget.",
        "steps": [
            "Select the primary provider and enter the key securely.",
            "Choose the fast-agent provider for speed-first routes.",
            "Check Ollama and pull the required model if it is missing.",
            "Set the daily budget limit and write config.archon.yaml.",
        ],
        "prompts": {
            "primary_provider": "Primary provider",
            "primary_key": "Primary provider key",
            "fast_provider": "Fast-agent provider",
            "budget_limit": "Daily budget limit",
            "ollama_pull": "Pull missing Ollama model now",
        },
        "complete": "ARCHON is ready. Config saved to {config_path}. Validation status: {validation_status}.",
    },
    "approval_gate": {
        "title": "Approval Required",
        "body": "Agent {agent} requested {action} against {target}. Preview: {preview}",
        "prompt": "Approve this action",
        "countdown": "Auto-deny in {seconds}s",
        "approved": "Approval granted for {action}. Resuming execution.",
        "denied": "Approval denied for {action}. Execution stopped.",
        "timed_out": "Approval timed out for {action}. Execution stopped.",
    },
    "live_task": {
        "title": "Live Task",
        "status_label": "Status",
        "agent_label": "Active agent",
        "mode_label": "Mode",
        "cost_label": "Budget",
        "round_label": "Debate round",
        "event_label": "Latest event",
        "idle": "Waiting for orchestration events.",
    },
    "placeholder": {
        "title": "NOT IMPLEMENTED YET",
        "body": "{command} is registered, but the runtime path is not implemented yet.",
        "detail": "Today this command only confirms the planned surface area for the {module} drawer.",
        "next": "Run archon {module} to see status, command names, and the exact command path.",
    },
}
