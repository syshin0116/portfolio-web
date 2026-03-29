# Supabase Authentication Implementation (SYS-22)

## Overview
This document describes the implementation of Supabase authentication with Google OAuth (including One-Touch login) and GitHub OAuth for the AppHub portfolio platform.

## Features Implemented

### 1. Authentication Providers
- **Google OAuth**: Full OAuth flow with redirect
- **Google One-Touch Login**: Automatic sign-in using Google's One Tap API
- **GitHub OAuth**: Full OAuth flow with redirect

### 2. Authentication Flow
- User-friendly login page with provider selection
- Secure OAuth callback handling
- Session management with Supabase
- Automatic session refresh via middleware
- Error handling for failed authentication attempts

### 3. UI Components
- **Login Page** (`/login`): Beautiful authentication UI with provider buttons
- **User Menu**: Dropdown menu with user profile and logout
- **Navbar Integration**: Shows login button or user avatar based on auth state
- **Google One-Touch**: Automatic popup for returning users

## File Structure

```
/workspace/
├── app/
│   ├── layout.tsx                    # Updated with AuthProvider
│   ├── login/
│   │   └── page.tsx                  # Login page with OAuth buttons
│   └── auth/
│       ├── callback/
│       │   └── route.ts              # OAuth callback handler
│       └── auth-code-error/
│           └── page.tsx              # Error page for failed auth
├── components/
│   └── auth/
│       ├── GoogleOneTap.tsx          # Google One-Touch component
│       └── UserMenu.tsx              # User profile dropdown
├── contexts/
│   └── AuthContext.tsx               # Authentication context & hooks
├── lib/
│   └── supabase/
│       ├── client.ts                 # Browser Supabase client
│       ├── server.ts                 # Server Supabase client
│       └── middleware.ts             # Session management
├── middleware.ts                     # Next.js middleware for session refresh
└── .env.local.example               # Environment variables template
```

## Setup Instructions

### 1. Supabase Project Setup

1. **Create a Supabase project** at https://supabase.com
2. **Configure Authentication Providers**:

   **Google OAuth:**
   - Go to Authentication → Providers → Google
   - Enable Google provider
   - Add your Google OAuth credentials:
     - Client ID
     - Client Secret
   - Add authorized redirect URIs:
     - `http://localhost:3000/auth/callback` (development)
     - `https://yourdomain.com/auth/callback` (production)

   **GitHub OAuth:**
   - Go to Authentication → Providers → GitHub
   - Enable GitHub provider
   - Add your GitHub OAuth credentials:
     - Client ID
     - Client Secret
   - Add authorized callback URL

3. **Get Supabase credentials**:
   - Project URL: Found in Project Settings → API
   - Anon/Public Key: Found in Project Settings → API

### 2. Google Cloud Console Setup (for One-Touch Login)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create or select a project
3. Enable Google+ API
4. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized JavaScript origins:
     - `http://localhost:3000`
     - `https://yourdomain.com`
   - Authorized redirect URIs:
     - `https://your-project.supabase.co/auth/v1/callback`
5. Copy the Client ID for One-Touch login

### 3. GitHub OAuth App Setup

1. Go to GitHub Settings → Developer settings → OAuth Apps
2. Create a new OAuth App:
   - Application name: Your app name
   - Homepage URL: Your application URL
   - Authorization callback URL: `https://your-project.supabase.co/auth/v1/callback`
3. Copy the Client ID and generate a Client Secret

### 4. Environment Variables

Create a `.env.local` file in the root directory:

```bash
# Supabase Configuration
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key

# Google OAuth (for One-Touch login)
NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
```

### 5. Install Dependencies

Dependencies have already been installed:
```bash
npm install @supabase/supabase-js @supabase/ssr
```

### 6. Run the Application

```bash
npm run dev
```

Visit `http://localhost:3000/login` to test the authentication.

## Usage

### Using Authentication in Components

```tsx
'use client'

import { useAuth } from '@/contexts/AuthContext'

export default function MyComponent() {
  const { user, loading, signInWithGoogle, signInWithGithub, signOut } = useAuth()

  if (loading) {
    return <div>Loading...</div>
  }

  if (!user) {
    return (
      <div>
        <button onClick={signInWithGoogle}>Sign in with Google</button>
        <button onClick={signInWithGithub}>Sign in with GitHub</button>
      </div>
    )
  }

  return (
    <div>
      <p>Welcome, {user.email}!</p>
      <button onClick={signOut}>Sign out</button>
    </div>
  )
}
```

### Protected Routes (Server Components)

```tsx
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

export default async function ProtectedPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  return <div>Protected content for {user.email}</div>
}
```

## Authentication Flow Details

### 1. OAuth Flow (Google & GitHub)
```
User clicks "Sign in with Google/GitHub"
  ↓
Redirects to provider's OAuth consent screen
  ↓
User authorizes the application
  ↓
Provider redirects to /auth/callback with code
  ↓
Callback handler exchanges code for session
  ↓
User is redirected to home page (authenticated)
```

### 2. Google One-Touch Flow
```
User visits login page
  ↓
Google One-Tap script loads
  ↓
Google shows one-tap prompt (if user previously signed in)
  ↓
User clicks to continue
  ↓
Component receives ID token
  ↓
Supabase validates token and creates session
  ↓
User is redirected to home page (authenticated)
```

### 3. Session Management
```
Middleware intercepts all requests
  ↓
Checks for valid session
  ↓
Refreshes session if needed
  ↓
Updates cookies
  ↓
Continues request
```

## Security Considerations

1. **Environment Variables**: Never commit `.env.local` to version control
2. **HTTPS**: Always use HTTPS in production
3. **Redirect URIs**: Only whitelist trusted redirect URIs
4. **Session Refresh**: Handled automatically by middleware
5. **Token Storage**: Tokens stored securely in HTTP-only cookies

## Troubleshooting

### Issue: "Invalid redirect URI"
- Ensure the redirect URI in your OAuth app settings matches exactly with your Supabase callback URL

### Issue: Google One-Touch not showing
- Check that `NEXT_PUBLIC_GOOGLE_CLIENT_ID` is set correctly
- Verify the client ID matches your Google Cloud Console credentials
- Ensure authorized JavaScript origins are configured

### Issue: Session not persisting
- Check that middleware is running (configured in `middleware.ts`)
- Verify cookies are not blocked in browser
- Check that environment variables are set correctly

### Issue: "Authentication code error"
- The OAuth code may have expired (codes are single-use)
- Try the authentication flow again
- Check Supabase logs for detailed error messages

## Testing

1. **Test Google OAuth**:
   - Navigate to `/login`
   - Click "Continue with Google"
   - Complete OAuth flow
   - Verify you're redirected and logged in

2. **Test GitHub OAuth**:
   - Navigate to `/login`
   - Click "Continue with GitHub"
   - Complete OAuth flow
   - Verify you're redirected and logged in

3. **Test Google One-Touch**:
   - Sign in with Google once
   - Sign out
   - Refresh the `/login` page
   - One-Touch prompt should appear automatically

4. **Test Session Persistence**:
   - Sign in
   - Close browser
   - Reopen and visit site
   - Should still be logged in

5. **Test Sign Out**:
   - Click user avatar in navbar
   - Click "Sign out"
   - Verify you're logged out

## Future Enhancements

- [ ] Add email/password authentication
- [ ] Implement password reset flow
- [ ] Add user profile editing
- [ ] Implement email verification
- [ ] Add two-factor authentication
- [ ] Add social profile information sync
- [ ] Implement role-based access control (RBAC)
- [ ] Add authentication analytics

## References

- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Supabase SSR Guide](https://supabase.com/docs/guides/auth/server-side/nextjs)
- [Google One Tap Documentation](https://developers.google.com/identity/gsi/web/guides/overview)
- [Next.js Authentication Patterns](https://nextjs.org/docs/app/building-your-application/authentication)
