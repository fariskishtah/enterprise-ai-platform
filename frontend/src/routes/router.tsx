import { createBrowserRouter } from "react-router-dom";

import { Dashboard } from "../pages/Dashboard";

export const router = createBrowserRouter([
  {
    element: <Dashboard />,
    path: "/",
  },
]);
