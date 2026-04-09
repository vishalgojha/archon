// Archon Cult UI Components
// AI-powered UI components from cult-ui, adapted for Archon
//
// Usage: These components are used in Archon's web dashboard
// to provide a production-ready AI chat interface.
//
// Dependencies:
//   npm install @ai-sdk/react ai lucide-react
//
// Import from here:
//   import { ArchonChat } from 'archon/interfaces/web/cult-ui'
//
// Components included:
//   - agent.tsx         Agent status indicator
//   - message.tsx       Chat message bubble (user/assistant)
//   - prompt-input.tsx  Text input with attachment support
//   - model-selector.tsx LLM model picker
//   - conversation.tsx  Scrollable message list
//   - chain-of-thought.tsx  Expandable reasoning display
//   - artifact.tsx      Code/file artifact display
//   - code-block.tsx    Syntax-highlighted code
//   - tool.tsx          Tool call display
//   - attachments.tsx   File attachment UI
//   - canvas.tsx        Canvas/artifact workspace
//   - panel.tsx         Side panel layout

export { Agent } from './components/agent'
export { Message, MessageContent } from './components/message'
export { PromptInput, PromptInputTextarea, PromptInputActions } from './components/prompt-input'
export { ModelSelector } from './components/model-selector'
export { Conversation } from './components/conversation'
export { ChainOfThought, ChainOfThoughtTrigger } from './components/chain-of-thought'
export { Artifact, ArtifactCode, ArtifactImage, ArtifactText } from './components/artifact'
export { CodeBlock } from './components/code-block'
export { Tool, ToolHeader, ToolContent, ToolInput, ToolOutput } from './components/tool'
export { Attachment, AttachmentProvider } from './components/attachments'
export { Canvas } from './components/canvas'
export { Panel, PanelHeader, PanelBody, PanelFooter } from './components/panel'
