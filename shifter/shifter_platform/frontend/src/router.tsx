import { createBrowserRouter } from "react-router-dom";

import { RootLayout } from "@/app/RootLayout";
import { RiskDetailPage } from "@/features/risk-register/RiskDetailPage";
import { RiskFormPage } from "@/features/risk-register/RiskFormPage";
import { RiskListPage } from "@/features/risk-register/RiskListPage";

// Mounted under the SPA-owned prefix; the Django host serves the shell for any
// sub-path so deep links and refresh resolve to the client router.
export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <RootLayout />,
      children: [
        { index: true, element: <RiskListPage /> },
        { path: "risks/create", element: <RiskFormPage mode="create" /> },
        { path: "risks/:id", element: <RiskDetailPage /> },
        { path: "risks/:id/edit", element: <RiskFormPage mode="edit" /> },
      ],
    },
  ],
  { basename: "/risk-register" },
);
