"use client"

import { Button, buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { type VariantProps } from "class-variance-authority"

export type PromptSuggestionProps = {
  children: React.ReactNode
  variant?: VariantProps<typeof buttonVariants>["variant"]
  size?: VariantProps<typeof buttonVariants>["size"]
  className?: string
} & React.ButtonHTMLAttributes<HTMLButtonElement>

function PromptSuggestion({
  children,
  variant,
  size,
  className,
  ...props
}: PromptSuggestionProps) {
  return (
    <Button
      variant={variant || "outline"}
      size={size || "lg"}
      className={cn("rounded-full", className)}
      {...props}
    >
      {children}
    </Button>
  )
}

export { PromptSuggestion }
