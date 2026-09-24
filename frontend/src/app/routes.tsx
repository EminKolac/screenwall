import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { HomeView } from "../features/library/HomeView";
import { ReviewWorkspace } from "../features/review/ReviewWorkspace";
import { NotFoundView } from "./NotFoundView";
import { CHAT_SEGMENT, docPath } from "./paths";
import { Shell } from "./Shell";

function ReviewRoute() {
  const { id = "", tab } = useParams();
  if (tab && tab !== CHAT_SEGMENT) return <Navigate to={docPath(id)} replace />;
  return <ReviewWorkspace key={id} docId={id} tab={tab === CHAT_SEGMENT ? "chat" : "findings"} />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomeView />} />
        <Route path="d/:id/:tab?" element={<ReviewRoute />} />
        <Route path="*" element={<NotFoundView />} />
      </Route>
    </Routes>
  );
}
