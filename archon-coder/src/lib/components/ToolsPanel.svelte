<script lang="ts">
    import { invoke } from '$lib/tauri-api';
    import { onMount } from 'svelte';

    export let onClose: () => void = () => {};

    type Tab = 'terminal' | 'git' | 'chat' | 'search' | 'tests' | 'scaffold' | 'fetch' | 'review' | 'security' | 'optimize' | 'fix' | 'arch' | 'schema' | 'prefs';
    let activeTab: Tab = 'terminal';

    // Terminal
    let cwd = '';
    let cmdInput = '';
    let cmdOutput = '';
    let cmdHistory: { cmd: string; output: string; ok: boolean }[] = [];
    let isRunningCmd = false;

    // Git
    let gitCwd = '';
    let gitOutput = '';
    let gitAction = 'status';

    // Chat
    let chatModel = 'qwen2.5:3b';
    let chatInput = '';
    let chatHistory: { role: string; content: string }[] = [];
    let isChatting = false;
    let availableModels: string[] = [];

    // Search
    let searchCwd = '';
    let searchPattern = '';
    let searchExt = '';
    let searchResults: string[] = [];

    // Tests
    let testCwd = '';
    let testFramework = 'npm';
    let testOutput = '';
    let isRunningTests = false;

    // Scaffold
    let scaffoldCwd = '';
    let scaffoldTemplate = 'node';
    let scaffoldName = '';
    let scaffoldOutput = '';

    // Fetch
    let fetchUrl = '';
    let fetchOutput = '';
    let isFetching = false;

    // Review
    let reviewCwd = '';
    let reviewFile = '';
    let reviewOutput = '';
    let isReviewing = false;

    // Security
    let securityCwd = '';
    let securityOutput = '';
    let isScanning = false;

    // Optimize
    let optimizeFile = '';
    let optimizeOutput = '';
    let isOptimizing = false;

    // Auto-fix
    let fixError = '';
    let fixOutput = '';
    let isFixing = false;

    // Architecture
    let archRequirements = '';
    let archLanguage = 'typescript';
    let archOutput = '';
    let isDesigning = false;

    // Schema
    let schemaTableName = '';
    let schemaFields = '';
    let schemaDbType = 'sql';
    let schemaOutput = '';
    let isGeneratingSchema = false;

    // Preferences
    let prefKey = '';
    let prefValue = '';
    let prefOutput = '';
    let isSavingPref = false;

    onMount(async () => {
        // Get current directory
        try {
            const result = await invoke<any>('run_command', { cmd: 'echo %CD%', cwd: null });
            cwd = result.output?.trim() || 'C:\\';
            gitCwd = cwd;
            searchCwd = cwd;
            testCwd = cwd;
            scaffoldCwd = cwd;
        } catch {
            cwd = 'C:\\';
        }
        
        // Get available models
        try {
            const result = await invoke<any>('check_ollama');
            if (result.ok && result.data?.models) {
                availableModels = result.data.models;
                chatModel = availableModels[0] || 'qwen2.5:3b';
            }
        } catch {}
    });

    // Terminal functions
    async function runCommand() {
        if (!cmdInput.trim() || isRunningCmd) return;
        isRunningCmd = true;
        const cmd = cmdInput;
        cmdInput = '';
        
        try {
            const result = await invoke<any>('run_command', { cmd, cwd });
            cmdOutput = result.output || result.error || 'No output';
            cmdHistory = [...cmdHistory, { cmd, output: result.output || '', ok: result.ok }];
        } catch (e: any) {
            cmdOutput = 'Error: ' + e.message;
        }
        isRunningCmd = false;
    }

    // Git functions
    async function runGit() {
        gitOutput = 'Running...';
        try {
            let result;
            switch (gitAction) {
                case 'status':
                    result = await invoke<any>('git_status', { cwd: gitCwd });
                    break;
                case 'branch':
                    result = await invoke<any>('git_branch', { cwd: gitCwd });
                    break;
                case 'log':
                    result = await invoke<any>('git_log', { cwd: gitCwd, limit: 10 });
                    break;
                default:
                    result = { ok: false, error: 'Unknown action' };
            }
            gitOutput = result.output || result.error || 'No output';
        } catch (e: any) {
            gitOutput = 'Error: ' + e.message;
        }
    }

    async function gitCommit() {
        const msg = prompt('Commit message:');
        if (!msg) return;
        gitOutput = 'Committing...';
        try {
            const result = await invoke<any>('git_commit', { cwd: gitCwd, message: msg });
            gitOutput = result.output || result.error || 'Done';
        } catch (e: any) {
            gitOutput = 'Error: ' + e.message;
        }
    }

    // Chat functions
    async function sendChat() {
        if (!chatInput.trim() || isChatting) return;
        isChatting = true;
        const userMsg = chatInput;
        chatHistory = [...chatHistory, { role: 'user', content: userMsg }];
        chatInput = '';
        
        try {
            const result = await invoke<any>('ollama_chat', { model: chatModel, prompt: userMsg });
            if (result.ok && result.output) {
                chatHistory = [...chatHistory, { role: 'assistant', content: result.output }];
            } else {
                chatHistory = [...chatHistory, { role: 'assistant', content: result.error || 'No response' }];
            }
        } catch (e: any) {
            chatHistory = [...chatHistory, { role: 'assistant', content: 'Error: ' + e.message }];
        }
        isChatting = false;
    }

    // Search functions
    async function doSearch() {
        if (!searchPattern.trim()) return;
        searchResults = [];
        try {
            const result = await invoke<any>('search_files', { cwd: searchCwd, pattern: searchPattern, ext: searchExt || null });
            searchResults = (result.output || '').split('\n').filter((l: string) => l.trim());
        } catch (e: any) {
            searchResults = ['Error: ' + e.message];
        }
    }

    // Test functions
    async function runTests() {
        isRunningTests = true;
        testOutput = 'Running tests...';
        try {
            const result = await invoke<any>('run_tests', { cwd: testCwd, framework: testFramework });
            testOutput = result.output || result.error || 'No output';
        } catch (e: any) {
            testOutput = 'Error: ' + e.message;
        }
        isRunningTests = false;
    }

    // Scaffold functions
    async function scaffold() {
        if (!scaffoldName.trim()) return;
        scaffoldOutput = 'Creating project...';
        try {
            const result = await invoke<any>('scaffold_project', { cwd: scaffoldCwd, template: scaffoldTemplate, name: scaffoldName });
            scaffoldOutput = result.output || result.error || 'Created!';
        } catch (e: any) {
            scaffoldOutput = 'Error: ' + e.message;
        }
    }

    async function installDeps() {
        if (!scaffoldName.trim()) return;
        scaffoldOutput = 'Installing...';
        try {
            const result = await invoke<any>('install_deps', { cwd: scaffoldCwd + '\\' + scaffoldName, manager: scaffoldTemplate === 'node' ? 'npm' : scaffoldTemplate });
            scaffoldOutput = result.output || result.error || 'Done!';
        } catch (e: any) {
            scaffoldOutput = 'Error: ' + e.message;
        }
    }

    async function doFetch() {
        if (!fetchUrl.trim()) return;
        isFetching = true;
        fetchOutput = 'Fetching...';
        try {
            const result = await invoke<any>('web_fetch', { url: fetchUrl });
            fetchOutput = result.output || result.error || 'No content';
        } catch (e: any) {
            fetchOutput = 'Error: ' + e.message;
        }
        isFetching = false;
    }

    async function doFetchJson() {
        if (!fetchUrl.trim()) return;
        isFetching = true;
        fetchOutput = 'Fetching JSON...';
        try {
            const result = await invoke<any>('web_fetch_json', { url: fetchUrl });
            fetchOutput = JSON.stringify(result.data || result.error, null, 2);
        } catch (e: any) {
            fetchOutput = 'Error: ' + e.message;
        }
        isFetching = false;
    }

    // Review functions
    async function doReview() {
        if (!reviewFile.trim()) return;
        isReviewing = true;
        reviewOutput = 'Reviewing code...';
        try {
            const result = await invoke<any>('review_code', { cwd: reviewCwd, file_path: reviewFile });
            reviewOutput = result.output || result.error || 'No issues found';
        } catch (e: any) {
            reviewOutput = 'Error: ' + e.message;
        }
        isReviewing = false;
    }

    // Security scan
    async function doSecurityScan() {
        isScanning = true;
        securityOutput = 'Scanning for security issues...';
        try {
            const result = await invoke<any>('security_scan', { cwd: securityCwd });
            securityOutput = result.output || result.error || 'No issues found';
        } catch (e: any) {
            securityOutput = 'Error: ' + e.message;
        }
        isScanning = false;
    }

    // Optimize code
    async function doOptimize() {
        if (!optimizeFile.trim()) return;
        isOptimizing = true;
        optimizeOutput = 'Optimizing...';
        try {
            const result = await invoke<any>('optimize_code', { file_path: optimizeFile });
            optimizeOutput = result.output || result.error || 'Optimized!';
        } catch (e: any) {
            optimizeOutput = 'Error: ' + e.message;
        }
        isOptimizing = false;
    }

    // Auto-fix
    async function doAutoFix() {
        if (!fixError.trim()) return;
        isFixing = true;
        fixOutput = 'Analyzing error...';
        try {
            const result = await invoke<any>('auto_fix', { cwd: reviewCwd, error_output: fixError });
            fixOutput = result.output || result.error || 'No fix found';
        } catch (e: any) {
            fixOutput = 'Error: ' + e.message;
        }
        isFixing = false;
    }

    // Architecture design
    async function doDesignArchitecture() {
        if (!archRequirements.trim()) return;
        isDesigning = true;
        archOutput = 'Designing architecture...';
        try {
            const result = await invoke<any>('design_architecture', { requirements: archRequirements, language: archLanguage });
            archOutput = result.output || result.error || 'Done';
        } catch (e: any) {
            archOutput = 'Error: ' + e.message;
        }
        isDesigning = false;
    }

    // Schema generation
    async function doGenerateSchema() {
        if (!schemaTableName.trim()) return;
        isGeneratingSchema = true;
        schemaOutput = 'Generating schema...';
        try {
            const fields = schemaFields.split(',').map(f => {
                const [name, type] = f.trim().split(':').map(s => s.trim());
                return { name, type: type || 'string' };
            });
            const result = await invoke<any>('generate_schema', { table_name: schemaTableName, fields, db_type: schemaDbType });
            schemaOutput = result.output || result.error || 'Generated!';
        } catch (e: any) {
            schemaOutput = 'Error: ' + e.message;
        }
        isGeneratingSchema = false;
    }

    // Preferences
    async function doSavePref() {
        if (!prefKey.trim()) return;
        isSavingPref = true;
        prefOutput = 'Saving...';
        try {
            const result = await invoke<any>('save_preference', { key: prefKey, value: JSON.parse(prefValue || '{}') });
            prefOutput = result.output || 'Saved!';
        } catch (e: any) {
            prefOutput = 'Error: ' + e.message;
        }
        isSavingPref = false;
    }

    async function doGetPref() {
        if (!prefKey.trim()) return;
        prefOutput = 'Loading...';
        try {
            const result = await invoke<any>('get_preference', { key: prefKey });
            prefOutput = JSON.stringify(result.data || result.output || 'Not found', null, 2);
        } catch (e: any) {
            prefOutput = 'Error: ' + e.message;
        }
    }
</script>

<div class="tools-panel">
    <div class="header">
        <div class="tabs">
            <button class:active={activeTab === 'terminal'} on:click={() => activeTab = 'terminal'}>Terminal</button>
            <button class:active={activeTab === 'git'} on:click={() => activeTab = 'git'}>Git</button>
            <button class:active={activeTab === 'chat'} on:click={() => activeTab = 'chat'}>Chat</button>
            <button class:active={activeTab === 'search'} on:click={() => activeTab = 'search'}>Search</button>
            <button class:active={activeTab === 'tests'} on:click={() => activeTab = 'tests'}>Tests</button>
            <button class:active={activeTab === 'scaffold'} on:click={() => activeTab = 'scaffold'}>Scaffold</button>
            <button class:active={activeTab === 'fetch'} on:click={() => activeTab = 'fetch'}>Fetch</button>
            <button class:active={activeTab === 'review'} on:click={() => activeTab = 'review'}>Review</button>
            <button class:active={activeTab === 'security'} on:click={() => activeTab = 'security'}>Security</button>
            <button class:active={activeTab === 'optimize'} on:click={() => activeTab = 'optimize'}>Optimize</button>
            <button class:active={activeTab === 'fix'} on:click={() => activeTab = 'fix'}>Fix</button>
            <button class:active={activeTab === 'arch'} on:click={() => activeTab = 'arch'}>Arch</button>
            <button class:active={activeTab === 'schema'} on:click={() => activeTab = 'schema'}>Schema</button>
            <button class:active={activeTab === 'prefs'} on:click={() => activeTab = 'prefs'}>Prefs</button>
        </div>
        <button class="close" on:click={onClose}>×</button>
    </div>

    <div class="content">
        <!-- Terminal -->
        {#if activeTab === 'terminal'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={cwd} placeholder="Working directory" class="cwd-input" />
                </div>
                <div class="output-area">
                    {#each cmdHistory as h}
                        <div class="history-item">
                            <span class="prompt">$</span> {h.cmd}
                            {#if h.output}<pre>{h.output}</pre>{/if}
                        </div>
                    {/each}
                    {#if cmdOutput}<pre>{cmdOutput}</pre>{/if}
                </div>
                <div class="input-row">
                    <span class="prompt">$</span>
                    <input bind:value={cmdInput} on:keydown={(e) => e.key === 'Enter' && runCommand()} placeholder="Command..." disabled={isRunningCmd} />
                </div>
            </div>
        {/if}

        <!-- Git -->
        {#if activeTab === 'git'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={gitCwd} placeholder="Repository path" class="cwd-input" />
                </div>
                <div class="row">
                    <select bind:value={gitAction}>
                        <option value="status">Status</option>
                        <option value="branch">Branches</option>
                        <option value="log">Log</option>
                    </select>
                    <button on:click={runGit}>Run</button>
                    <button on:click={gitCommit}>Commit</button>
                </div>
                <pre class="output-area">{gitOutput}</pre>
            </div>
        {/if}

        <!-- Chat -->
        {#if activeTab === 'chat'}
            <div class="tab-content">
                <div class="row">
                    <select bind:value={chatModel}>
                        {#each availableModels as m}<option value={m}>{m}</option>{/each}
                    </select>
                </div>
                <div class="chat-history">
                    {#each chatHistory as msg}
                        <div class="chat-msg {msg.role}">
                            <span class="role">{msg.role === 'user' ? '>' : '<'}</span>
                            {msg.content}
                        </div>
                    {/each}
                </div>
                <div class="input-row">
                    <input bind:value={chatInput} on:keydown={(e) => e.key === 'Enter' && sendChat()} placeholder="Ask anything..." disabled={isChatting} />
                    <button on:click={sendChat} disabled={isChatting}>Send</button>
                </div>
            </div>
        {/if}

        <!-- Search -->
        {#if activeTab === 'search'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={searchCwd} placeholder="Directory" class="cwd-input" />
                </div>
                <div class="row">
                    <input bind:value={searchPattern} placeholder="Pattern" />
                    <input bind:value={searchExt} placeholder="ext (e.g. ts)" style="width: 60px" />
                    <button on:click={doSearch}>Search</button>
                </div>
                <div class="results">
                    {#each searchResults as r}
                        <div class="result-item">{r}</div>
                    {/each}
                </div>
            </div>
        {/if}

        <!-- Tests -->
        {#if activeTab === 'tests'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={testCwd} placeholder="Project directory" class="cwd-input" />
                </div>
                <div class="row">
                    <select bind:value={testFramework}>
                        <option value="npm">npm (JS)</option>
                        <option value="pytest">pytest (Python)</option>
                        <option value="cargo">cargo (Rust)</option>
                        <option value="go">go test</option>
                    </select>
                    <button on:click={runTests} disabled={isRunningTests}>{isRunningTests ? 'Running...' : 'Run Tests'}</button>
                </div>
                <pre class="output-area">{testOutput}</pre>
            </div>
        {/if}

        <!-- Scaffold -->
        {#if activeTab === 'scaffold'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={scaffoldCwd} placeholder="Parent directory" class="cwd-input" />
                </div>
                <div class="row">
                    <select bind:value={scaffoldTemplate}>
                        <option value="node">Node.js</option>
                        <option value="react">React</option>
                        <option value="next">Next.js</option>
                        <option value="rust">Rust</option>
                        <option value="python">Python</option>
                    </select>
                    <input bind:value={scaffoldName} placeholder="Project name" />
                </div>
                <div class="row">
                    <button on:click={scaffold}>Create</button>
                    <button on:click={installDeps}>Install Deps</button>
                </div>
                <pre class="output-area">{scaffoldOutput}</pre>
            </div>
        {/if}

        <!-- Fetch -->
        {#if activeTab === 'fetch'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={fetchUrl} placeholder="https://api.example.com/data" class="cwd-input" />
                </div>
                <div class="row">
                    <button on:click={doFetch} disabled={isFetching}>{isFetching ? 'Fetching...' : 'GET'}</button>
                    <button on:click={doFetchJson} disabled={isFetching}>JSON</button>
                </div>
                <div class="output-area fetch-output">
                    {#if fetchOutput}
                        {fetchOutput}
                    {:else}
                        <span class="placeholder">Enter URL and click fetch...</span>
                    {/if}
                </div>
            </div>
        {/if}

        <!-- Code Review -->
        {#if activeTab === 'review'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={reviewCwd} placeholder="Working directory" class="cwd-input" />
                </div>
                <div class="row">
                    <input bind:value={reviewFile} placeholder="File path to review" class="cwd-input" />
                </div>
                <div class="row">
                    <button on:click={doReview} disabled={isReviewing}>{isReviewing ? 'Reviewing...' : 'Review Code'}</button>
                </div>
                <pre class="output-area">{reviewOutput}</pre>
            </div>
        {/if}

        <!-- Security Scan -->
        {#if activeTab === 'security'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={securityCwd} placeholder="Directory to scan" class="cwd-input" />
                </div>
                <div class="row">
                    <button on:click={doSecurityScan} disabled={isScanning}>{isScanning ? 'Scanning...' : 'Scan'}</button>
                </div>
                <pre class="output-area">{securityOutput}</pre>
            </div>
        {/if}

        <!-- Optimize -->
        {#if activeTab === 'optimize'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={optimizeFile} placeholder="File to optimize" class="cwd-input" />
                </div>
                <div class="row">
                    <button on:click={doOptimize} disabled={isOptimizing}>{isOptimizing ? 'Optimizing...' : 'Optimize'}</button>
                </div>
                <pre class="output-area">{optimizeOutput}</pre>
            </div>
        {/if}

        <!-- Auto-fix -->
        {#if activeTab === 'fix'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={reviewCwd} placeholder="Working directory" class="cwd-input" />
                </div>
                <div class="row">
                    <textarea bind:value={fixError} placeholder="Paste error message..." class="cwd-input" rows="4"></textarea>
                </div>
                <div class="row">
                    <button on:click={doAutoFix} disabled={isFixing}>{isFixing ? 'Fixing...' : 'Auto Fix'}</button>
                </div>
                <pre class="output-area">{fixOutput}</pre>
            </div>
        {/if}

        <!-- Architecture -->
        {#if activeTab === 'arch'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={archLanguage} placeholder="Language" class="cwd-input" style="width: 100px" />
                </div>
                <div class="row">
                    <textarea bind:value={archRequirements} placeholder="Describe requirements..." class="cwd-input" rows="4"></textarea>
                </div>
                <div class="row">
                    <button on:click={doDesignArchitecture} disabled={isDesigning}>{isDesigning ? 'Designing...' : 'Design'}</button>
                </div>
                <pre class="output-area">{archOutput}</pre>
            </div>
        {/if}

        <!-- Schema -->
        {#if activeTab === 'schema'}
            <div class="tab-content">
                <div class="row">
                    <select bind:value={schemaDbType} style="width: 100px">
                        <option value="sql">SQL</option>
                        <option value="prisma">Prisma</option>
                        <option value="mongoose">Mongoose</option>
                    </select>
                    <input bind:value={schemaTableName} placeholder="Table name" class="cwd-input" />
                </div>
                <div class="row">
                    <input bind:value={schemaFields} placeholder="name:type, age:number" class="cwd-input" />
                </div>
                <div class="row">
                    <button on:click={doGenerateSchema} disabled={isGeneratingSchema}>{isGeneratingSchema ? 'Generating...' : 'Generate'}</button>
                </div>
                <pre class="output-area">{schemaOutput}</pre>
            </div>
        {/if}

        <!-- Preferences -->
        {#if activeTab === 'prefs'}
            <div class="tab-content">
                <div class="row">
                    <input bind:value={prefKey} placeholder="Key" class="cwd-input" />
                </div>
                <div class="row">
                    <textarea bind:value={prefValue} placeholder="JSON Value" class="cwd-input" rows="3"></textarea>
                </div>
                <div class="row">
                    <button on:click={doSavePref} disabled={isSavingPref}>Save</button>
                    <button on:click={doGetPref}>Load</button>
                </div>
                <pre class="output-area">{prefOutput}</pre>
            </div>
        {/if}
    </div>
</div>

<style>
    .tools-panel {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        margin: 8px 0;
        max-height: 500px;
        display: flex;
        flex-direction: column;
    }
    .header {
        display: flex;
        align-items: center;
        padding: 8px;
        border-bottom: 1px solid #30363d;
        background: #161b22;
    }
    .tabs {
        display: flex;
        gap: 4px;
        flex: 1;
    }
    .tabs button {
        background: transparent;
        border: none;
        color: #8b949e;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 12px;
        cursor: pointer;
    }
    .tabs button.active {
        background: #21262d;
        color: #f0f6fc;
    }
    .close {
        background: transparent;
        border: none;
        color: #8b949e;
        font-size: 18px;
        cursor: pointer;
    }
    .content {
        flex: 1;
        overflow-y: auto;
        padding: 12px;
    }
    .tab-content {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    .row {
        display: flex;
        gap: 8px;
        align-items: center;
    }
    .cwd-input {
        flex: 1;
        background: #0d1117;
        border: 1px solid #30363d;
        color: #c9d1d9;
        padding: 6px 10px;
        border-radius: 4px;
        font-size: 12px;
        font-family: monospace;
    }
    input, select {
        background: #0d1117;
        border: 1px solid #30363d;
        color: #c9d1d9;
        padding: 6px 10px;
        border-radius: 4px;
        font-size: 12px;
    }
    button {
        background: #238636;
        border: none;
        color: white;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 12px;
        cursor: pointer;
    }
    button:hover { background: #2ea043; }
    button:disabled { opacity: 0.5; }
    .output-area {
        background: #0d1117;
        border: 1px solid #30363d;
        padding: 10px;
        border-radius: 4px;
        font-family: monospace;
        font-size: 11px;
        color: #8b949e;
        white-space: pre-wrap;
        max-height: 200px;
        overflow-y: auto;
    }
    .prompt { color: #58a6ff; font-weight: bold; }
    .history-item { margin-bottom: 8px; }
    .history-item pre { margin: 4px 0; }
    .chat-history {
        max-height: 180px;
        overflow-y: auto;
        margin-bottom: 8px;
    }
    .chat-msg {
        padding: 6px 10px;
        margin-bottom: 4px;
        border-radius: 4px;
        font-size: 12px;
    }
    .chat-msg.user { background: #1f6feb; color: white; }
    .chat-msg.assistant { background: #21262d; color: #c9d1d9; }
    .chat-msg .role { font-weight: bold; margin-right: 8px; }
    .input-row {
        display: flex;
        gap: 8px;
        align-items: center;
    }
    .input-row input { flex: 1; }
    .results {
        max-height: 150px;
        overflow-y: auto;
    }
    .result-item {
        padding: 4px 8px;
        font-family: monospace;
        font-size: 11px;
        color: #8b949e;
        cursor: pointer;
    }
    .result-item:hover { background: #21262d; }
</style>