import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth";
import { HomePage } from "./HomePage";
import { LoginPage } from "./LoginPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<HomePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
