import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth";
import { LoginPage } from "./LoginPage";
import { DeskHome } from "./QueuePage";
import { RequestPage } from "./RequestPage";
import { UsersPage } from "./UsersPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<DeskHome />} />
        <Route path="/requests/:requestId" element={<RequestPage />} />
        <Route path="/users" element={<UsersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
