'use client'

import { SessionProvider, useSession, signIn, signOut } from 'next-auth/react'
import { createContext, useContext } from 'react'

interface AuthContextType {
  user: {
    id?: string
    name?: string | null
    email?: string | null
    image?: string | null
  } | null
  loading: boolean
  signInWithGoogle: () => Promise<void>
  signInWithGithub: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

function AuthContextInner({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession()
  const loading = status === 'loading'
  const user = session?.user ?? null

  const signInWithGoogle = async () => {
    await signIn('google', { redirectTo: '/' })
  }

  const signInWithGithub = async () => {
    await signIn('github', { redirectTo: '/' })
  }

  const handleSignOut = async () => {
    await signOut({ redirectTo: '/' })
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, signInWithGoogle, signInWithGithub, signOut: handleSignOut }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AuthContextInner>{children}</AuthContextInner>
    </SessionProvider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
