<script lang="ts">
    import { invoke } from '$lib/tauri-api';
    import { onMount } from 'svelte';

    let cwd = '';
    let command = '';
    let output = '';
    let isRunning = false;
    let history: { cmd: string; output: string; ok: boolean }[] = [];

    onMount(async () => {
        // Get current directory
        try {
            const result = await invoke<any>('run_command', { cmd: 'echo %CD%', cwd: null });
            cwd = result.output?.trim() || 'C:\\';
        } catch {
            cwd = 'C:\\';
        }
    });

    async function run() {
        if (!command.trim() || isRunning) return;
        
        isRunning = true;
        const cmd = command;
        command = '';
        
        try {
            const result = await invoke<any>('run_command', { cmd, cwd });
            output = result.output || result.error || 'No output';
            history = [...history, { cmd, output: result.output || '', ok: result.ok }];
            document.dispatchEvent(new CustomEvent('archon-log', { 
                detail: { type: result.ok ? 'info' : 'error', msg: `Shell: ${result.ok ? 'OK' : 'Error'}` } 
            }));
        } catch (e: any) {
            output = 'Error: ' + e.message;
            history = [...history, { cmd, output: e.message, ok: false }];
        }
        
        isRunning = false;
    }

    function clearOutput() {
        output = '';
        history = [];
    }
</script>

<div class="terminal-panel">
    <div class="header">
        <span class="title">Terminal</span>
        <span class="cwd">{cwd}</span>
        <button on:click={clearOutput}>Clear</button>
    </div>
    
    <div class="output">
        {#each history as h}
            <div class="history-item">
                <span class="prompt">{'>'}</span>
                <span class="cmd">{h.cmd}</span>
                {#if h.output}
                    <pre class="result" class:error={!h.ok}>{h.output}</pre>
                {/if}
            </div>
        {/each}
        {#if output}
            <pre class="result">{output}</pre>
        {/if}
    </div>
    
    <div class="input-line">
        <span class="prompt">{'>'}</span>
        <input 
            bind:value={command} 
            on:keydown={(e) => e.key === 'Enter' && run()}
            placeholder="Enter command..."
            disabled={isRunning}
        />
    </div>
</div>

<style>
    .terminal-panel {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        margin: 8px 0;
        max-height: 400px;
        display: flex;
        flex-direction: column;
    }
    
    .header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 12px;
        border-bottom: 1px solid #30363d;
        background: #161b22;
    }
    
    .title {
        font-weight: 600;
        font-size: 12px;
        color: #f0f6fc;
    }
    
    .cwd {
        flex: 1;
        font-size: 11px;
        color: #8b949e;
        font-family: monospace;
    }
    
    .header button {
        background: transparent;
        border: 1px solid #30363d;
        color: #8b949e;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 11px;
        cursor: pointer;
    }
    
    .output {
        flex: 1;
        overflow-y: auto;
        padding: 12px;
        font-family: monospace;
        font-size: 12px;
        min-height: 150px;
        max-height: 250px;
    }
    
    .history-item {
        margin-bottom: 8px;
    }
    
    .prompt {
        color: #58a6ff;
        font-weight: bold;
        margin-right: 8px;
    }
    
    .cmd {
        color: #c9d1d9;
    }
    
    .result {
        margin: 4px 0 0 20px;
        white-space: pre-wrap;
        color: #8b949e;
        font-size: 11px;
    }
    
    .result.error {
        color: #f85149;
    }
    
    .input-line {
        display: flex;
        align-items: center;
        padding: 8px 12px;
        border-top: 1px solid #30363d;
        background: #161b22;
    }
    
    .input-line input {
        flex: 1;
        background: transparent;
        border: none;
        color: #c9d1d9;
        font-family: monospace;
        font-size: 12px;
        outline: none;
    }
</style>