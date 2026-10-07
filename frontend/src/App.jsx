import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import { EmptyState } from "./components/States.jsx";
import { ButtonLink } from "./components/ui.jsx";
import CreateIncident from "./pages/CreateIncident.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Identities from "./pages/Identities.jsx";
import IncidentDetail from "./pages/IncidentDetail.jsx";
import IncidentList from "./pages/IncidentList.jsx";
import Scenarios from "./pages/Scenarios.jsx";

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you are looking for does not exist."
      action={<ButtonLink to="/">Back to dashboard</ButtonLink>}
    />
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="incidents" element={<IncidentList />} />
        <Route path="incidents/new" element={<CreateIncident />} />
        <Route path="incidents/:id" element={<IncidentDetail />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="identities" element={<Identities />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
