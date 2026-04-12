<script lang="ts">
    import { invoke } from '$lib/tauri-api';

    let entries: any[] = [];
    let currentPath = '';
    let loading = false;

    async function listDir(path: string) {
        loading = true;
        try {
            const result = await invoke<any>('list_directory', { path });
            console.log('[FileTree] Result:', result);
            
            // Handle both string and object responses
            let data = result;
            if (typeof result === 'string') {
                data = JSON.parse(result);
            }
            
            entries = data.data?.entries || data.entries || [];
            currentPath = data.data?.path || data.path || path;
            document.dispatchEvent(new CustomEvent('archon-log', { detail: { type: 'info', msg: 'Files loaded: ' + entries.length + ' items' } }));
        } catch (e: any) {
            console.error('[FileTree] Error:', e);
            document.dispatchEvent(new CustomEvent('archon-log', { detail: { type: 'error', msg: 'Files: ' + e.message } }));
        }
        loading = false;
    }

    async function openInExplorer() {
        const pathToOpen = currentPath || '.';
        try {
            await invoke('open_path', { path: pathToOpen });
            document.dispatchEvent(new CustomEvent('archon-log', { detail: { type: 'info', msg: 'Opened: ' + pathToOpen } }));
        } catch (e: any) {
            console.error('Failed to open path:', e);
            document.dispatchEvent(new CustomEvent('archon-log', { detail: { type: 'error', msg: 'Open failed: ' + e.message } }));
        }
    }

    // Default to home directory
    listDir('.');
</script>

<aside class="panel">
    <div class="header">
        <h3>Files</h3>
        <div class="actions">
            <button on:click={() => listDir(currentPath || '.')} title="Refresh">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M23 4v6h-6M1 20v-6h6"/>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                </svg>
            </button>
            <button on:click={openInExplorer} title="Open in Explorer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
            </button>
        </div>
    </div>
    <div class="content">
        {#if loading}
            <div class="loading">Loading...</div>
        {:else if currentPath}
            <div class="path">{currentPath}</div>
        {/if}
        {#each entries as entry}
            <div class="entry {entry.is_dir ? 'dir' : 'file'}"
                 on:click={() => entry.is_dir && listDir(currentPath ? `${currentPath}/${entry.name}` : entry.name)}>
                <span class="icon">{entry.is_dir ? '>' : '-'}</span>
                <span class="name">{entry.name}</span>
                {#if !entry.is_dir && entry.size > 0}
                    <span class="size">{(entry.size / 1024).toFixed(1)}KB</span>
                {/if}
            </div>
        {/each}
    </div>
</aside>

<style>
    .panel {
        width: 240px;
        background: #18181b;
        border-right: 1px solid #27272a;
        display: flex;
        flex-direction: column;
        flex-shrink: 0;
    }
    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        border-bottom: 1px solid #27272a;
    }
    .header h3 { 
        font-size: 13px; 
        font-weight: 600; 
        color: #fafafa;
        margin: 0;
    }
    .actions {
        display: flex;
        gap: 4px;
    }
    .header button {
        background: transparent;
        border: none;
        color: #71717a;
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .header button:hover { 
        background: #27272a; 
        color: #fafafa; 
    }
    .content { 
        flex: 1; 
        overflow-y: auto; 
        padding: 8px; 
        font-family: monospace; 
        font-size: 12px; 
    }
    .path {
        padding: 4px 8px;
        color: #71717a;
        font-size: 11px;
        margin-bottom: 4px;
        word-break: break-all;
    }
    .entry {
        padding: 4px 8px;
        cursor: pointer;
        border-radius: 4px;
        color: #fafafa;
        transition: background 0.15s;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .entry:hover { background: #27272a; }
    .entry.dir { color: #22c55e; }
    .entry.file { color: #a1a1aa; }
    .icon {
        width: 14px;
        text-align: center;
        color: #71717a;
    }
    .name {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .size { 
        color: #52525b; 
        font-size: 10px; 
        margin-left: auto; 
    }
    .loading { 
        text-align: center; 
        color: #52525b; 
        padding: 24px; 
        font-size: 12px; 
    }
</style>