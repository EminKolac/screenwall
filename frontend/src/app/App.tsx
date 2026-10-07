import { useEffect, useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { captureLaunchToken } from "../api/client";
import { createQueryClient } from "../api/queries";
import { ToastProvider } from "../ui/Toast";
import { AppRoutes } from "./routes";
import { ThemeProvider } from "./theme";

export function App() {
  const [queryClient] = useState(createQueryClient);
  useEffect(() => {
    // The launcher may open its address, with a new launch token, in a tab that already shows the
    // app: only the fragment changes and the page does not reload. Take the token and refetch.
    const onHashChange = () => {
      if (captureLaunchToken()) void queryClient.invalidateQueries();
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [queryClient]);
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <AppRoutes />
          </BrowserRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
