'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card'
import { FaGoogle, FaGithub } from 'react-icons/fa'
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
      <main className="min-h-screen flex items-center justify-center">
        <div
          role="status"
          aria-label="로그인 상태 확인 중"
          className="animate-spin motion-reduce:animate-none rounded-full h-12 w-12 border-b-2 border-gray-900 dark:border-white"
        />
      </main>
    )
  }

  if (user) {
    return null
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-4">
          <div className="flex justify-center">
            <Link href="/" className="flex items-center gap-2">
              <Image
                src="/logo.png"
                width={48}
                height={48}
                alt="Syshin0116 홈"
                className="h-12 w-12 rounded-lg object-contain"
              />
            </Link>
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-bold">Welcome back</h1>
            <CardDescription className="text-base mt-2">
              Sign in to your account to continue
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            onClick={() => signInWithGoogle()}
            variant="outline"
            className="w-full h-12 text-base font-medium"
          >
            <FaGoogle className="mr-3 h-5 w-5" />
            Continue with Google
          </Button>

          <Button
            onClick={() => signInWithGithub()}
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
    </main>
  )
}
