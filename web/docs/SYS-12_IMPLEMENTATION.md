# SYS-12: 홈 아이콘 /home으로 Route Implementation

## Issue Description
- **Title**: 홈 아이콘 /home으로 Route (Route home icon to /home)
- **Description**: 홈 아이콘 클릭 시 채팅 내용 초기화 (Reset chat content when home icon is clicked)

## Implementation Summary

This implementation adds functionality to reset the chat content when the home icon is clicked.

### Changes Made

#### 1. `components/chat-section.tsx`
- Added `useSearchParams` from `next/navigation` to detect URL query parameters
- Added `useEffect` hook that watches for `reset=true` query parameter
- When reset parameter is detected:
  - Clears all chat messages (`setChatMessages([])`)
  - Resets the prompt input (`setPrompt("")`)
  - Resets loading state (`setIsLoading(false)`)
  - Cleans up the URL by removing the query parameter using `window.history.replaceState`

#### 2. `components/navbar/navbar.tsx`
- Added `usePathname` and `useRouter` hooks from `next/navigation`
- Created `handleHomeClick` function that:
  - Prevents default link behavior
  - Checks if user is already on home page (`pathname === '/'`)
  - If on home page: navigates to `/?reset=true` to trigger chat reset
  - If on another page: navigates to `/` normally
- Applied the `handleHomeClick` handler to:
  - Desktop logo (top-left)
  - Desktop "Home" navigation menu item
  - Mobile logo
  - Mobile "Home" link in sheet menu
  - Mobile logo in sheet header

#### 3. `app/page.tsx`
- Wrapped `ChatSection` component in a `Suspense` boundary
- This is required for components using `useSearchParams` in Next.js 15+
- Added a simple loading fallback to handle the suspense state

## How It Works

1. User clicks the home icon/logo or "Home" navigation item
2. `handleHomeClick` function is triggered
3. If already on home page (`/`):
   - Navigates to `/?reset=true`
   - `ChatSection` detects the `reset=true` parameter via `useSearchParams`
   - Chat state is cleared (messages, prompt, loading state)
   - URL is cleaned up to just `/`
4. If on another page:
   - Simply navigates to `/` (normal navigation)

## Testing

The implementation was tested by:
1. Running TypeScript compilation - ✅ No errors
2. Running ESLint - ✅ No linting errors
3. Running production build - ✅ Build successful
4. All static pages generated correctly

## Technical Notes

- Used query parameters instead of state management for simplicity
- The `Suspense` boundary is required for SSR compatibility with `useSearchParams`
- The implementation works for both desktop and mobile views
- The URL cleanup ensures a clean user experience (no lingering query parameters)

## Files Modified

1. `/workspace/components/chat-section.tsx` - Added reset logic
2. `/workspace/components/navbar/navbar.tsx` - Added home click handler
3. `/workspace/app/page.tsx` - Added Suspense boundary

## Build Output

```
Route (app)                                 Size  First Load JS
┌ ○ /                                     136 kB         284 kB
├ ○ /_not-found                             1 kB         107 kB
├ ○ /projects                            38.5 kB         186 kB
└ ● /projects/[projectId]                5.71 kB         153 kB
```

All pages compiled successfully with no errors.
