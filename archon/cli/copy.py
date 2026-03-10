DRAWER_COPY = {
    "core": {
        "title": "Core Control",
        "icon": "[C]",
        "tagline": "Bring ARCHON up, inspect runtime state, and enter chat.",
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
            "core.chat": "Launch the existing ARCHON chat and TUI experience.",
        },
    },
    "agents": {
        "title": "Agent Sessions",
        "icon": "[A]",
        "tagline": "Run debate, direct tasks, and terminal sessions against live agents.",
        "availability": "live",
        "explanation": (
            "Agent session commands expose the current orchestration entry points: a "
            "single task call, a local debate or growth run, and the full interactive "
            "terminal interface."
        ),
        "requires": ["validated config", "BYOK or Ollama access"],
        "commands": {
            "agents.task": "Send one goal through the API task surface.",
            "agents.debate": "Run a local orchestration pass without HTTP.",
            "agents.tui": "Open the interactive terminal session for ARCHON.",
        },
    },
    "growth": {
        "title": "Growth Swarm",
        "icon": "[G]",
        "tagline": "Drive the seven-agent revenue and distribution workflow.",
        "availability": "live",
        "explanation": (
            "Growth commands route work through Prospector, ICP, Outreach, Nurture, "
            "Revenue Intel, Partner, and Churn Defense so operators can inspect "
            "distribution planning from the CLI control plane."
        ),
        "requires": ["growth-capable config", "budget headroom"],
        "commands": {
            "growth.run": "Execute a goal directly in growth mode.",
        },
    },
    "vision": {
        "title": "Vision Runtime",
        "icon": "[V]",
        "tagline": "Screen understanding, UI parsing, and action planning.",
        "availability": "live",
        "explanation": (
            "The vision stack covers capture, UI parsing, action generation, recovery, "
            "and audit traces for screen-driven automation. Use inspect to parse the "
            "current screen and act to trigger approved UI interactions."
        ),
        "requires": ["desktop session", "vision provider routing"],
        "commands": {
            "vision.inspect": "Inspect the active screen and UI structure.",
            "vision.act": "Plan or execute a vision-guided UI action.",
        },
    },
    "web": {
        "title": "Web Intelligence",
        "icon": "[W]",
        "tagline": "Crawl, classify, and optimize websites from one drawer.",
        "availability": "staged",
        "explanation": (
            "The web stack combines crawling, intent classification, injection "
            "generation, and optimization helpers for research and site-level execution. "
            "The drawer is present now while command implementations are staged."
        ),
        "requires": ["network access", "web provider routing"],
        "commands": {
            "web.crawl": "Crawl a target site and extract structured findings.",
            "web.optimize": "Generate optimization actions from web intelligence.",
        },
    },
    "memory": {
        "title": "Memory Stack",
        "icon": "[M]",
        "tagline": "Search stored context and manage memory exports.",
        "availability": "partial",
        "explanation": (
            "Memory commands expose the tenant-safe store behind ARCHON recalls, letting "
            "operators search persisted context today and reserve an export surface for "
            "governed data movement."
        ),
        "requires": ["memory database", "tenant identifier for scoped reads"],
        "commands": {
            "memory.search": "Query memory by tenant and ranked similarity.",
            "memory.export": "Export a tenant memory namespace for audit or transfer.",
        },
    },
    "evolve": {
        "title": "Evolution Engine",
        "icon": "[E]",
        "tagline": "Stage experiments, compare candidates, and promote winners.",
        "availability": "staged",
        "explanation": (
            "The evolution stack handles A/B staging, audit trails, and controlled "
            "workflow promotion. The CLI drawer is exposed ahead of the final operator "
            "commands so the control plane stays consistent."
        ),
        "requires": ["evolution policy", "audit trail storage"],
        "commands": {
            "evolve.plan": "Stage an evolution candidate and preview the experiment.",
            "evolve.apply": "Promote or roll back an approved evolution result.",
        },
    },
    "federation": {
        "title": "Federation",
        "icon": "[F]",
        "tagline": "Discover peers and exchange patterns across ARCHON nodes.",
        "availability": "staged",
        "explanation": (
            "Federation links ARCHON runtimes for peer discovery, collaborative solves, "
            "and pattern sharing. This drawer exposes the future CLI surface while the "
            "dedicated commands remain staged."
        ),
        "requires": ["peer registry", "network reachability"],
        "commands": {
            "federation.peers": "Inspect federation peers and capabilities.",
            "federation.sync": "Sync shared patterns and federation state.",
        },
    },
    "providers": {
        "title": "Providers",
        "icon": "[P]",
        "tagline": "Inspect BYOK routing and test provider health in place.",
        "availability": "live",
        "explanation": (
            "Provider commands read the active config and environment so operators can "
            "see role assignments, confirm which providers are actually wired, and run "
            "real health probes with measured latency."
        ),
        "requires": ["config.archon.yaml", "provider keys in environment"],
        "commands": {
            "providers.list": "Show the configured provider assigned to each role.",
            "providers.test": "Run live provider health checks and latency probes.",
        },
    },
    "marketplace": {
        "title": "Marketplace",
        "icon": "[K]",
        "tagline": "Developer revenue, payouts, and partner operations.",
        "availability": "staged",
        "explanation": (
            "Marketplace operations cover onboarding, revenue share, payout cycles, and "
            "partner reporting. The drawer is visible so finance and partner operators "
            "see the control plane before the dedicated CLI paths go live."
        ),
        "requires": ["marketplace databases", "approval gate for financial actions"],
        "commands": {
            "marketplace.payouts": "Inspect or run marketplace payout workflows.",
            "marketplace.earnings": "Review marketplace earnings and revenue share.",
        },
    },
    "studio": {
        "title": "Studio",
        "icon": "[S]",
        "tagline": "Open the visual workflow surface and run saved workflows.",
        "availability": "live",
        "explanation": (
            "Studio commands connect the CLI to the saved workflow system so operators "
            "can open the browser-based editor or trigger an existing workflow run from "
            "the same control plane."
        ),
        "requires": ["running API server", "studio workflow storage"],
        "commands": {
            "studio.open": "Open ARCHON Studio in the browser.",
            "studio.run": "Run a saved workflow file through the runtime.",
        },
    },
    "ops": {
        "title": "Operations",
        "icon": "[O]",
        "tagline": "Serve APIs, watch health, and manage background workers.",
        "availability": "live",
        "explanation": (
            "Operations commands cover the API server, health surfaces, observability, "
            "and the SQLite-backed deployment worker that drains queued tasks from the "
            "active runtime directory."
        ),
        "requires": ["runtime directory", "worker queue database when enabled"],
        "commands": {
            "ops.serve": "Start the ARCHON API server.",
            "ops.health": "Check API health from the CLI.",
            "ops.monitor": "Render a live metrics and traces monitor.",
            "ops.worker": "Start the deployment worker and stream its logs.",
            "ops.worker-status": "Read worker queue counts from the runtime database.",
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
        "what": "Inspect the active ARCHON runtime by reading config, runtime directory, and worker queue state.",
        "steps": [
            "Resolve the active config file and runtime directory.",
            "Read version and provider role assignments.",
            "Inspect the worker queue database for pending and active tasks.",
            "Render the runtime summary for operators.",
        ],
        "results": {
            "success": "ARCHON {version} using runtime {runtime_dir}. Queue depth: {queue_depth}. Active workers: {worker_count}.",
        },
        "next_steps": [
            "Run archon ops worker-status for queue detail.",
            "Run archon providers test if provider health looks stale.",
            "Run archon core chat to interact with the runtime.",
        ],
    },
    "core.chat": {
        "what": "Enter the existing ARCHON terminal chat path and route work through the live TUI session.",
        "steps": [
            "Load the active config and initial mode.",
            "Prepare onboarding callbacks and session context.",
            "Launch the current TUI or chat entry path.",
        ],
        "results": {
            "success": "Chat session exited cleanly for mode {mode}.",
        },
        "next_steps": [
            "Run archon core status to inspect runtime state after the session.",
            "Run archon agents.task for one-off API tasks.",
        ],
    },
    "agents.task": {
        "what": "Send one goal to the ARCHON API task endpoint with tenant auth and structured context.",
        "steps": [
            "Resolve the task mode from the goal and requested mode.",
            "Build tenant auth headers and task context.",
            "Post the task to the running API.",
            "Render the final answer, confidence, and budget usage.",
        ],
        "results": {
            "success": "Task completed in {mode} mode with confidence {confidence}% and spend {spent_usd}.",
        },
        "next_steps": [
            "Run archon ops.monitor to watch runtime activity.",
            "Run archon growth run for a growth-only local pass.",
        ],
    },
    "agents.debate": {
        "what": "Run a local orchestration pass without HTTP and return the final answer directly in the terminal.",
        "steps": [
            "Load config and resolve the effective mode.",
            "Start the orchestrator with the selected provider mode.",
            "Execute the goal locally and capture budget data.",
            "Close shared provider resources cleanly.",
        ],
        "results": {
            "success": "Local run completed in {mode} mode with confidence {confidence}% and spend {spent_usd}.",
        },
        "next_steps": [
            "Run archon core chat for an interactive session.",
            "Run archon ops.monitor to inspect observability output.",
        ],
    },
    "agents.tui": {
        "what": "Open the interactive terminal session with launcher controls, context editing, approvals, and transcript output.",
        "steps": [
            "Load config or wizard defaults.",
            "Resolve live provider mode and initial context.",
            "Attach onboarding callbacks.",
            "Launch the agentic TUI.",
        ],
        "results": {
            "success": "TUI session closed cleanly with mode {mode}.",
        },
        "next_steps": [
            "Run archon core status to inspect runtime state.",
            "Run archon ops.serve if you want HTTP access next.",
        ],
    },
    "growth.run": {
        "what": "Run a goal directly through the seven-agent growth swarm and return prioritized actions.",
        "steps": [
            "Load config and start the orchestrator.",
            "Execute the goal in growth mode.",
            "Collect action recommendations and budget usage.",
            "Close the orchestrator cleanly.",
        ],
        "results": {
            "success": "Growth swarm completed with confidence {confidence}% and {action_count} recommended actions.",
        },
        "next_steps": [
            "Run archon agents.task with --mode growth for API execution.",
            "Run archon ops.monitor to watch live system activity.",
        ],
    },
    "vision.inspect": {
        "what": "Inspect the active screen and extract UI structure through the vision runtime.",
        "steps": [
            "Capture a screenshot or load an image from file or clipboard.",
            "Select the vision provider and model based on config and keys.",
            "Parse visible UI elements into a structured layout.",
            "Render the detected UI elements and metadata.",
        ],
        "results": {
            "success": "Vision inspection parsed {element_count} elements using {provider}/{model}.",
            "failure": "Vision inspection failed. {error}",
        },
        "next_steps": [
            "Run archon vision act to interact with a UI element.",
            "Save a screenshot and use --file for repeatable inspection.",
        ],
    },
    "vision.act": {
        "what": "Plan or execute a UI action through the vision action stack.",
        "steps": [
            "Capture a screenshot and parse the UI layout.",
            "Identify the target element for the instruction.",
            "Request approval before executing UI actions.",
            "Execute the action and capture confirmation screenshots.",
        ],
        "results": {
            "success": "Vision action '{action}' executed on {element_id} at ({x},{y}).",
            "failure": "Vision action failed. {error}",
        },
        "next_steps": [
            "Run archon vision inspect to confirm the UI state.",
            "Review approval history if actions were denied.",
        ],
    },
    "web.crawl": {
        "what": "Crawl a site and convert the response into structured web intelligence findings.",
        "steps": [
            "Reserve the command surface for the web crawl path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon web to review the planned control surface.",
        ],
    },
    "web.optimize": {
        "what": "Generate site optimization actions from the web intelligence stack.",
        "steps": [
            "Reserve the command surface for the web optimization path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon web to review the planned control surface.",
        ],
    },
    "memory.search": {
        "what": "Search the tenant-scoped memory store and render ranked results.",
        "steps": [
            "Load the config and open the memory store.",
            "Run similarity search for the requested tenant namespace.",
            "Render the result table and close the store.",
        ],
        "results": {
            "success": "Memory search returned {result_count} result(s) for tenant {tenant_id}.",
            "empty": "Memory search returned no results for tenant {tenant_id}.",
        },
        "next_steps": [
            "Refine the query or raise --top-k for broader recall.",
            "Run archon memory export when the governed export path is live.",
        ],
    },
    "memory.export": {
        "what": "Export a tenant memory namespace for review, transfer, or compliance workflows.",
        "steps": [
            "Reserve the command surface for the memory export path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon memory to review the available memory controls.",
        ],
    },
    "evolve.plan": {
        "what": "Stage an evolution candidate and prepare it for controlled A/B evaluation.",
        "steps": [
            "Reserve the command surface for the evolution staging path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon evolve to review the planned control surface.",
        ],
    },
    "evolve.apply": {
        "what": "Promote or roll back an evolved workflow after review.",
        "steps": [
            "Reserve the command surface for the evolution apply path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon evolve to review the planned control surface.",
        ],
    },
    "federation.peers": {
        "what": "Inspect peer state and capabilities across the federation layer.",
        "steps": [
            "Reserve the command surface for the federation peer path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon federation to review the planned control surface.",
        ],
    },
    "federation.sync": {
        "what": "Sync patterns and shared state across connected ARCHON peers.",
        "steps": [
            "Reserve the command surface for the federation sync path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon federation to review the planned control surface.",
        ],
    },
    "providers.list": {
        "what": "Read the active config and environment to show how provider roles are currently assigned.",
        "steps": [
            "Load the active config file.",
            "Resolve each BYOK role to its configured provider.",
            "Check whether the required environment key is present.",
            "Render the provider role table.",
        ],
        "results": {
            "success": "Rendered {provider_count} provider role assignments from the active config.",
        },
        "next_steps": [
            "Run archon providers test to probe live health and latency.",
            "Run archon core validate after changing provider roles.",
        ],
    },
    "providers.test": {
        "what": "Run real health probes for the configured providers and report response latency.",
        "steps": [
            "Load config and determine which providers require probes.",
            "Ping each configured provider endpoint.",
            "Measure latency and collect health status.",
            "Render the provider health table.",
        ],
        "results": {
            "success": "Provider tests completed for {provider_count} provider(s). Passing: {pass_count}.",
            "failure": "Provider tests completed for {provider_count} provider(s). Passing: {pass_count}.",
        },
        "next_steps": [
            "Fix unreachable or auth-failed providers before production use.",
            "Run archon core status to confirm runtime context.",
        ],
    },
    "marketplace.payouts": {
        "what": "Inspect or execute marketplace payout workflows for developers and partners.",
        "steps": [
            "Reserve the command surface for the marketplace payout path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon marketplace to review the planned control surface.",
        ],
    },
    "marketplace.earnings": {
        "what": "Review revenue share and earnings output from the marketplace ledger.",
        "steps": [
            "Reserve the command surface for the marketplace earnings path.",
        ],
        "results": {
            "success": "{command} is reserved for the {module} module.",
        },
        "next_steps": [
            "Run archon marketplace to review the planned control surface.",
        ],
    },
    "studio.open": {
        "what": "Open the Studio browser surface after confirming the ARCHON API is reachable.",
        "steps": [
            "Check the API health endpoint.",
            "Open the Studio route in the default browser.",
        ],
        "results": {
            "success": "Studio opened at {url}.",
        },
        "next_steps": [
            "Run archon studio run to execute a saved workflow file.",
            "Run archon ops.health if the browser surface does not load.",
        ],
    },
    "studio.run": {
        "what": "Execute a workflow file through the existing runtime path and print the outcome.",
        "steps": [
            "Load config and parse the workflow file.",
            "Decide between dry-run preview and live execution.",
            "Run the workflow through the orchestrator when live execution is requested.",
            "Render the workflow result.",
        ],
        "results": {
            "success": "Workflow {workflow_name} completed in {mode} mode.",
            "dry_run": "Workflow {workflow_name} contains {step_count} step(s).",
        },
        "next_steps": [
            "Open Studio if you want to edit the workflow visually.",
            "Run archon ops.monitor while executing longer workflows.",
        ],
    },
    "ops.serve": {
        "what": "Start the ARCHON API server with the active config and runtime environment.",
        "steps": [
            "Ensure a config file exists, onboarding if needed.",
            "Load environment variables and config.",
            "Start the API server.",
        ],
        "results": {
            "success": "ARCHON API server started on {host}:{port}.",
        },
        "next_steps": [
            "Run archon ops.health to verify the server.",
            "Run archon studio open or archon agents.task once the server is live.",
        ],
    },
    "ops.health": {
        "what": "Check the health endpoint for the running ARCHON API and summarize the response.",
        "steps": [
            "Request the API health endpoint.",
            "Render server status, version, git SHA, database state, and uptime.",
        ],
        "results": {
            "success": "Server status is {status}. Version: {version}. Database: {db_status}.",
        },
        "next_steps": [
            "Run archon ops.monitor for a continuous view.",
            "Run archon ops.serve if the server is down.",
        ],
    },
    "ops.monitor": {
        "what": "Render a live terminal monitor from health, metrics, and trace endpoints.",
        "steps": [
            "Poll health, metrics, and trace endpoints.",
            "Summarize request rate, error rate, sessions, approvals, and recent spans.",
            "Refresh the live monitor until the operator stops it.",
        ],
        "results": {
            "success": "Monitor session stopped after {iteration_count} refresh cycle(s).",
        },
        "next_steps": [
            "Run archon ops.health for a single-shot status check.",
            "Run archon core.chat to drive new workload through the runtime.",
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
            "Run archon ops.worker-status to inspect queue progress.",
            "Run archon ops.monitor to inspect API-side activity.",
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
            "Run archon ops.worker to start or restart the worker.",
            "Run archon core.status for the broader runtime summary.",
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
