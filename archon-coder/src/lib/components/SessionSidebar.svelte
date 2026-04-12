<script lang="ts">
    import { invoke } from '$lib/tauri-api';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher();
    export let activeSessionId: string | null = null;

    let sessions: any[] = [];
    let showNewModal = false;
    let newName = '';
    let newMode = 'isolated';

    async function loadSessions() {
        try {
            const raw = await invoke<string>('list_sessions', {});
            const parsed = JSON.parse(raw);
            sessions = Array.isArray(parsed) ? parsed : (parsed.data || []);
        } catch (e) {
            sessions = [];
        }
    }

    async function createSession() {
        try {
            const raw = await invoke<string>('create_session', {
                name: newName || 'Untitled',
                mode: newMode,
                path: null,
            });
            const result = JSON.parse(raw);
            activeSessionId = result.session_id;
            showNewModal = false;
            newName = '';
            dispatch('session-created', result);
            await loadSessions();
        } catch (e) {
            console.error('Failed to create session:', e);
        }
    }

    async function switchSession(id: string) {
        activeSessionId = id;
        dispatch('session-selected', id);
    }

    loadSessions();

    $: if (activeSessionId) {
        // Could highlight active
    }
</script>

<aside class="sidebar">
    <div class="header">
        <h3>Sessions</h3>
        <button on:click={() => showNewModal = true}>+ New</button>
    </div>

    <div class="list">
        {#if sessions.length === 0}
            <div class="empty">No sessions yet.</div>
        {:else}
            {#each sessions as s}
                <div
                    class="session-item {activeSessionId === s.id ? 'active' : ''}"
                    on:click={() => switchSession(s.id)}
                >
                    <div class="name">{s.name}</div>
                    <div class="meta">{s.mode} Â· {s.message_count || 0} msgs</div>
                </div>
            {/each}
        {/if}
    </div>

    {#if showNewModal}
        <div class="modal-backdrop" on:click={() => showNewModal = false}>
            <div class="modal" on:click|stopPropagation>
                <h3>New Session</h3>
                <label>
                    Name
                    <input bind:value={newName} placeholder="My project..." />
                </label>
                <label>
                    Mode
                    <select bind:value={newMode}>
                        <option value="isolated">Isolated (new project dir)</option>
                        <option value="shared">Shared (existing workspace)</option>
                    </select>
                </label>
                <div class="actions">
                    <button on:click={() => showNewModal = false}>Cancel</button>
                    <button class="primary" on:click={createSession}>Create</button>
                </div>
            </div>
        </div>
    {/if}
</aside>

<style>
    .sidebar {
        width: 200px;
        background: var(--bg-secondary);
        border-right: 1px solid var(--border);
        display: flex;
        flex-direction: column;
        flex-shrink: 0;
    }
    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px;
        border-bottom: 1px solid var(--border);
    }
    .header h3 { font-size: 13px; font-weight: 600; }
    .header button {
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        color: var(--text);
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 11px;
        cursor: pointer;
    }
    .header button:hover { border-color: var(--blue); }
    .list { flex: 1; overflow-y: auto; padding: 8px; }
    .empty { text-align: center; color: var(--text-muted); padding: 24px 12px; font-size: 12px; }
    .session-item {
        padding: 8px 10px;
        border-radius: 6px;
        cursor: pointer;
        margin-bottom: 4px;
        transition: background 0.15s;
    }
    .session-item:hover { background: var(--bg-tertiary); }
    .session-item.active { background: var(--bg-tertiary); border-left: 2px solid var(--green); }
    .name { font-size: 12px; font-weight: 500; color: var(--text); }
    .meta { font-size: 10px; color: var(--text-dim); margin-top: 2px; }

    .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }
    .modal {
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 24px;
        width: 360px;
        max-width: 90vw;
    }
    .modal h3 { margin-bottom: 16px; font-size: 16px; }
    .modal label {
        display: block;
        margin-bottom: 12px;
        font-size: 12px;
        color: var(--text-dim);
    }
    .modal input, .modal select {
        width: 100%;
        margin-top: 4px;
        padding: 8px;
        background: var(--bg-primary);
        border: 1px solid var(--border);
        border-radius: 6px;
        color: var(--text);
        font-size: 13px;
    }
    .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
    .actions button {
        padding: 8px 16px;
        border-radius: 6px;
        border: 1px solid var(--border);
        background: var(--bg-tertiary);
        color: var(--text);
        cursor: pointer;
        font-size: 12px;
    }
    .actions button.primary {
        background: var(--blue);
        border-color: var(--blue);
        color: #fff;
    }
</style>
