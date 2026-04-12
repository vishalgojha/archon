<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import AgentsList from './AgentsList.svelte';
    import ContextsList from './ContextsList.svelte';

    export let agents: { name: string; color: string; initials: string }[] = [];
    export let contexts: string[] = [];
    export let activeAgent: { name: string; color: string; initials: string } | null = null;

    const dispatch = createEventDispatcher();

    const utilityItems = [
        { id: 'terminal', label: 'Terminal', icon: '⚡' },
        { id: 'files', label: 'Files', icon: '📁' },
        { id: 'settings', label: 'Settings', icon: '⚙' },
    ];
</script>

<aside class="sidebar">
    <div class="sidebar-top">
        <div class="logo-row">
            <span class="logo">⚡ Archon</span>
            <button class="search-btn" title="Search">⌕</button>
        </div>

        <AgentsList {agents} on:select={(e) => dispatch('agent-select', e.detail)} />
        <ContextsList {contexts} on:select={(e) => dispatch('context-select', e.detail)} />
    </div>

    <div class="sidebar-bottom">
        <div class="divider"></div>
        <div class="utility-links">
            {#each utilityItems as item}
                <button 
                    class="utility-btn"
                    on:click={() => dispatch('utility-click', item.id)}
                >
                    <span class="utility-icon">{item.icon}</span>
                    <span>{item.label}</span>
                </button>
            {/each}
        </div>
    </div>
</aside>

<style>
    .sidebar {
        width: 280px;
        min-width: 280px;
        background: #0A0A0A;
        border-right: 1px solid #1E1E1E;
        display: flex;
        flex-direction: column;
    }

    .sidebar-top {
        flex: 1;
        padding: 16px;
        overflow-y: auto;
    }

    .logo-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 24px;
    }

    .logo {
        font-weight: 700;
        font-size: 18px;
        color: #E8DCC8;
    }

    .search-btn {
        background: transparent;
        border: none;
        color: #E8DCC8;
        font-size: 20px;
        cursor: pointer;
        opacity: 0.6;
    }

    .search-btn:hover {
        opacity: 1;
    }

    .sidebar-bottom {
        padding: 12px 16px;
        border-top: 1px solid #1E1E1E;
    }

    .divider {
        height: 1px;
        background: #1E1E1E;
        margin-bottom: 12px;
    }

    .utility-links {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .utility-btn {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        background: transparent;
        border: none;
        color: #E8DCC8;
        font-size: 13px;
        cursor: pointer;
        border-radius: 6px;
        text-align: left;
    }

    .utility-btn:hover {
        background: #1E1E1E;
    }

    .utility-btn.active {
        background: #1E1E1E;
        border-left: 2px solid #7ee787;
    }

    .utility-icon {
        font-size: 14px;
    }
</style>