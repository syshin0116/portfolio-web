# Model Selection Button Implementation

## Issue: SYS-13 - 챗봇 UI 모델 선택 버튼 추가

### Implementation Summary

Added a model selection button to the chatbot UI with the following features:

#### 1. **Design**
- Uses shadcn-based Button component, consistent with other UI buttons
- Styled with `variant="outline"` and `className="rounded-full"` to match RAG setting buttons
- Includes Bot icon from lucide-react

#### 2. **Available Models**
The following models are defined in the `AVAILABLE_MODELS` constant:
- `gpt-4.1-nano` (default)
- `gpt-4o`
- `gpt-4.1`
- `gpt-4.1-mini`
- `gpt-5.1`
- `gpt-5.1-mini`
- `gpt-5.1-nano`

#### 3. **Current State**
- Button displays the currently selected model (`gpt-4.1-nano` by default)
- Button is **disabled** (`disabled={true}`) as per requirements
- Tooltip indicates "Model: {selectedModel} (selection coming soon)"

#### 4. **Location**
The button is placed in the prompt input actions area, after the RAG setting buttons (Metadata, Files, Vector, Graph) and before the Voice input button.

#### 5. **State Management**
- `selectedModel` state variable manages the current model selection
- `setSelectedModel` function prepared for future use when selection is enabled
- `AVAILABLE_MODELS` constant defined for future dropdown/select implementation

### Files Modified
- `components/chat-section.tsx`

### Future Enhancements
When model selection needs to be enabled:
1. Create a dropdown/select component (or add shadcn's Select component)
2. Remove the `disabled={true}` prop
3. Implement onClick handler to show model selection dropdown
4. Use `AVAILABLE_MODELS` constant to populate the dropdown options
5. Update `setSelectedModel` to handle model changes
6. Pass selected model to the API client when making chat requests

### Testing
- Build successful: ✓
- TypeScript compilation: ✓
- Styling consistent with existing buttons: ✓
