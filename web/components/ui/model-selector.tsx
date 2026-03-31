"use client"

import { useState, useRef, useEffect } from "react"
import { ChevronDownIcon, CheckIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

export interface Model {
  id: string
  provider: string
  model_id: string
  display_name: string
  is_default: boolean
  enabled: boolean
}

interface ModelSelectorProps {
  models: Model[]
  selectedModelId: string
  onModelChange: (modelId: string) => void
  disabled?: boolean
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google_genai: "Google",
}

function groupByProvider(models: Model[]): Record<string, Model[]> {
  const groups: Record<string, Model[]> = {}
  for (const model of models) {
    const key = model.provider
    if (!groups[key]) groups[key] = []
    groups[key].push(model)
  }
  return groups
}

export function ModelSelector({ models, selectedModelId, onModelChange, disabled = false }: ModelSelectorProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const selected = models.find((m) => m.model_id === selectedModelId)
  const groups = groupByProvider(models)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="sm"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <span className="max-w-[160px] truncate">{selected?.display_name ?? "Select model"}</span>
        <ChevronDownIcon className={cn("size-3 transition-transform", open && "rotate-180")} />
      </Button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1 w-56 animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
          <div className="rounded-xl border border-border bg-popover p-1 shadow-lg">
            {Object.entries(groups).map(([provider, providerModels]) => (
              <div key={provider}>
                <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                  {PROVIDER_LABELS[provider] ?? provider}
                </div>
                {providerModels.map((model) => (
                  <button
                    key={model.model_id}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted",
                      model.model_id === selectedModelId && "bg-muted text-foreground"
                    )}
                    onClick={() => { onModelChange(model.model_id); setOpen(false) }}
                  >
                    <span className="flex-1 truncate">{model.display_name}</span>
                    {model.model_id === selectedModelId && <CheckIcon className="size-3.5 text-primary" />}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
