import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import "./index.css";

import { createQueryClient } from "@/api/queryClient";
import { applyInitialTheme } from "@/lib/theme";
import { router } from "@/router";

applyInitialTheme();

const queryClient = createQueryClient();
const container = document.getElementById("root");

if (container) {
  createRoot(container).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}
