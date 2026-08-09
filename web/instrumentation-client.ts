import { initBotId } from "botid/client/core"

initBotId({
  protect: [
    {
      path: "/api/anonymous-agent-token",
      method: "POST",
      advancedOptions: { checkLevel: "basic" },
    },
  ],
})
