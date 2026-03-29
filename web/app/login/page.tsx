'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { FaGoogle, FaGithub } from 'react-icons/fa'
import GoogleOneTap from '@/components/auth/GoogleOneTap'
import Image from 'next/image'
import Link from 'next/link'

export default function LoginPage() {
  const { user, loading, signInWithGoogle, signInWithGithub } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (user && !loading) {
      router.push('/')
    }
  }, [user, loading, router])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 dark:border-white"></div>
      </div>
    )
  }

  if (user) {
    return null
  }

  const handleGoogleSignIn = async () => {
    try {
      await signInWithGoogle()
    } catch (error) {
      console.error('Failed to sign in with Google:', error)
    }
  }

  const handleGithubSignIn = async () => {
    try {
      await signInWithGithub()
    } catch (error) {
      console.error('Failed to sign in with GitHub:', error)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800 p-4">
      <GoogleOneTap />
      
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-4">
          <div className="flex justify-center">
            <Link href="/" className="flex items-center gap-2">
              <Image
                src="/logo.png"
                width={48}
                height={48}
                alt="logo"
                className="rounded-lg"
              />
            </Link>
          </div>
          <div className="text-center">
            <CardTitle className="text-2xl font-bold">Welcome back</CardTitle>
            <CardDescription className="text-base mt-2">
              Sign in to your account to continue
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            onClick={handleGoogleSignIn}
            variant="outline"
            className="w-full h-12 text-base font-medium"
          >
            <FaGoogle className="mr-3 h-5 w-5" />
            Continue with Google
          </Button>
          
          <Button
            onClick={handleGithubSignIn}
            variant="outline"
            className="w-full h-12 text-base font-medium"
          >
            <FaGithub className="mr-3 h-5 w-5" />
            Continue with GitHub
          </Button>

          <div className="text-center text-sm text-muted-foreground pt-4">
            By continuing, you agree to our Terms of Service and Privacy Policy
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
