'use client'

import Script from 'next/script'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

interface CredentialResponse {
  credential: string
  select_by?: string
}

interface GoogleAccounts {
  id: {
    initialize: (config: {
      client_id: string
      callback: (response: CredentialResponse) => void
      nonce?: string
      use_fedcm_for_prompt?: boolean
    }) => void
    prompt: () => void
    cancel: () => void
  }
}

declare const google: { accounts: GoogleAccounts }

// Generate nonce to use for google id token sign-in
const generateNonce = async (): Promise<string[]> => {
  const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))
  const encoder = new TextEncoder()
  const encodedNonce = encoder.encode(nonce)
  const hashBuffer = await crypto.subtle.digest('SHA-256', encodedNonce)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  const hashedNonce = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
  return [nonce, hashedNonce]
}

export default function GoogleOneTap() {
  const supabase = createClient()
  const router = useRouter()

  if (!supabase) return null

  const initializeGoogleOneTap = () => {
    console.log('Initializing Google One Tap')

    // Async initialization wrapper
    ;(async () => {
      const [nonce, hashedNonce] = await generateNonce()
      console.log('Nonce generated')

      // Check if there's already an existing session before initializing the one-tap UI
      const { data, error } = await supabase.auth.getSession()
      if (error) {
        console.error('Error getting session', error)
      }
      if (data.session) {
        console.log('User already logged in, skipping One Tap')
        return
      }

      const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID
      if (!clientId) {
        console.warn('Google Client ID not configured')
        return
      }

      /* global google */
      google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response: CredentialResponse) => {
          try {
            console.log('Google One Tap callback triggered')
            // Send id token returned in response.credential to supabase
            const { data, error } = await supabase.auth.signInWithIdToken({
              provider: 'google',
              token: response.credential,
              nonce,
            })
            if (error) throw error
            console.log('Session data: ', data)
            console.log('Successfully logged in with Google One Tap')
            // Redirect to home page
            router.push('/')
            router.refresh()
          } catch (error) {
            console.error('Error logging in with Google One Tap', error)
          }
        },
        nonce: hashedNonce,
        // With chrome's removal of third-party cookies, we need to use FedCM instead
        use_fedcm_for_prompt: true,
      })
      google.accounts.id.prompt() // Display the One Tap UI
    })()
  }

  return <Script onReady={initializeGoogleOneTap} src="https://accounts.google.com/gsi/client" />
}
