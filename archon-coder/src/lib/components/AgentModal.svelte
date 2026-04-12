<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    
    export let agent: any;
    
    const dispatch = createEventDispatcher();
    
    let agentName = agent?.name || '';
    let selectedModel = 'ollama';
    let isPublic = false;
    let description = '';
    let goals = '';
</script>

<div class="modal-backdrop" on:click={() => dispatch('close')}>
    <div class="modal" on:click|stopPropagation>
        <div class="modal-header">
            <h2>Agent Details</h2>
            <button class="close-btn" on:click={() => dispatch('close')}>×</button>
        </div>
        
        <div class="field">
            <label for="name">Agent Name</label>
            <input id="name" type="text" bind:value={agentName} placeholder="Enter agent name..." />
        </div>
        
        <div class="field">
            <label for="model">Model</label>
            <select id="model" bind:value={selectedModel}>
                <option value="ollama">Ollama (Local)</option>
                <option value="groq">Groq</option>
                <option value="anthropic">Anthropic</option>
            </select>
        </div>
        
        <div class="field toggle-field">
            <label for="public">Public Agent</label>
            <button 
                class="toggle" 
                class:active={isPublic}
                on:click={() => isPublic = !isPublic}
            >
                <span class="toggle-knob"></span>
            </button>
        </div>
        
        <div class="field">
            <label for="description">Description</label>
            <textarea id="description" bind:value={description} placeholder="What does this agent do?"></textarea>
        </div>
        
        <div class="field">
            <label for="goals">Goals</label>
            <textarea id="goals" bind:value={goals} placeholder="Agent goals and objectives..."></textarea>
        </div>
        
        <div class="modal-actions">
            <button class="cancel-btn" on:click={() => dispatch('close')}>Cancel</button>
            <button class="save-btn">Save Changes</button>
        </div>
    </div>
</div>

<style>
    .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .modal {
        background: #0A0A0A;
        border: 1px solid #1E1E1E;
        border-radius: 12px;
        padding: 24px;
        width: 480px;
        max-width: 90vw;
    }

    .modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
    }

    .modal-header h2 {
        font-size: 18px;
        font-weight: 600;
        color: #E8DCC8;
        margin: 0;
    }

    .close-btn {
        background: transparent;
        border: none;
        color: #E8DCC8;
        font-size: 24px;
        cursor: pointer;
        opacity: 0.6;
    }

    .close-btn:hover {
        opacity: 1;
    }

    .field {
        margin-bottom: 16px;
    }

    .field label {
        display: block;
        font-size: 12px;
        color: #E8DCC8;
        opacity: 0.7;
        margin-bottom: 6px;
    }

    .field input, .field select, .field textarea {
        width: 100%;
        padding: 10px 12px;
        background: #1E1E1E;
        border: 1px solid #1E1E1E;
        border-radius: 6px;
        color: #E8DCC8;
        font-size: 13px;
        outline: none;
    }

    .field input:focus, .field select:focus, .field textarea:focus {
        border-color: #E8DCC8;
    }

    .field textarea {
        min-height: 80px;
        resize: vertical;
    }

    .toggle-field {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .toggle-field label {
        margin: 0;
    }

    .toggle {
        width: 44px;
        height: 24px;
        background: #1E1E1E;
        border: 1px solid #1E1E1E;
        border-radius: 12px;
        cursor: pointer;
        position: relative;
        transition: all 0.2s;
    }

    .toggle.active {
        background: #7ee787;
        border-color: #7ee787;
    }

    .toggle-knob {
        position: absolute;
        top: 3px;
        left: 3px;
        width: 16px;
        height: 16px;
        background: #E8DCC8;
        border-radius: 50%;
        transition: transform 0.2s;
    }

    .toggle.active .toggle-knob {
        transform: translateX(20px);
    }

    .modal-actions {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
        margin-top: 24px;
    }

    .cancel-btn {
        padding: 10px 20px;
        background: transparent;
        border: 1px solid #1E1E1E;
        border-radius: 6px;
        color: #E8DCC8;
        font-size: 13px;
        cursor: pointer;
    }

    .cancel-btn:hover {
        border-color: #E8DCC8;
    }

    .save-btn {
        padding: 10px 20px;
        background: #E8DCC8;
        border: none;
        border-radius: 6px;
        color: #0A0A0A;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
    }

    .save-btn:hover {
        background: #d4c9b5;
    }
</style>