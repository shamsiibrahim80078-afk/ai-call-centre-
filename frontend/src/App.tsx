import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import ProtectedRoute from "./components/ProtectedRoute";
import Landing from "./pages/Landing";
import MiniAppPage from "./pages/MiniAppPage";
import Dashboard from "./pages/Dashboard";
import VerifyPage from "./pages/VerifyPage";
import WorkforcePage from "./pages/WorkforcePage";
import IntegrationsPage from "./pages/IntegrationsPage";
import OpsCenterPage from "./pages/OpsCenterPage";
import AgentDetailPage from "./pages/AgentDetailPage";
import NewsPage from "./pages/NewsPage";
import MeetingPage from "./pages/MeetingPage";
import ReportsPage from "./pages/ReportsPage";
import JobsPage from "./pages/JobsPage";
import AccountPage from "./pages/AccountPage";
import CommandCenterPage from "./pages/CommandCenterPage";
import CollaborationHubPage from "./pages/CollaborationHubPage";
import LiveRequestsPage from "./pages/LiveRequestsPage";
import MarketIntelPage from "./pages/MarketIntelPage";
import CommsAssistantPage from "./pages/CommsAssistantPage";
import InvestigationPage from "./pages/InvestigationPage";
import BlockchainPage from "./pages/BlockchainPage";
import SettingsPage from "./pages/SettingsPage";
import LiveRuntimePage from "./pages/LiveRuntimePage";
import AICallingPage from "./pages/AICallingPage";
import MarketingAgencyPage from "./pages/MarketingAgencyPage";
import LaunchpadPage from "./pages/LaunchpadPage";
import PostingsPage from "./pages/PostingsPage";
import SignInPage from "./pages/SignInPage";
import SignUpPage from "./pages/SignUpPage";
import ThreadsOAuthCallbackPage from "./pages/ThreadsOAuthCallbackPage";

function Dash({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/mini" element={<MiniAppPage />} />
      <Route path="/sign-in/*" element={<SignInPage />} />
      <Route path="/sign-up/*" element={<SignUpPage />} />
      {/* Public Meta Threads OAuth callback — must stay outside ProtectedRoute */}
      <Route path="/oauth/threads/callback" element={<ThreadsOAuthCallbackPage />} />
      <Route path="/dashboard" element={<Dash><Dashboard /></Dash>} />
      <Route path="/dashboard/runtime" element={<Dash><LiveRuntimePage /></Dash>} />
      <Route path="/dashboard/live" element={<Dash><LiveRuntimePage /></Dash>} />
      <Route path="/dashboard/verify" element={<Dash><VerifyPage /></Dash>} />
      <Route path="/dashboard/investigation" element={<Dash><InvestigationPage /></Dash>} />
      <Route path="/dashboard/requests" element={<Dash><LiveRequestsPage /></Dash>} />
      <Route path="/dashboard/workforce" element={<Dash><WorkforcePage /></Dash>} />
      <Route path="/dashboard/workspace" element={<Navigate to="/dashboard/runtime" replace />} />
      <Route path="/dashboard/integrations" element={<Dash><IntegrationsPage /></Dash>} />
      <Route path="/dashboard/collaboration" element={<Dash><CollaborationHubPage /></Dash>} />
      <Route path="/dashboard/ops" element={<Dash><OpsCenterPage /></Dash>} />
      <Route path="/dashboard/command-center" element={<Dash><CommandCenterPage /></Dash>} />
      <Route path="/dashboard/market" element={<Dash><MarketIntelPage /></Dash>} />
      <Route path="/dashboard/meeting" element={<Dash><MeetingPage /></Dash>} />
      <Route path="/dashboard/news" element={<Dash><NewsPage /></Dash>} />
      <Route path="/dashboard/comms" element={<Dash><CommsAssistantPage /></Dash>} />
      <Route path="/dashboard/marketing" element={<Dash><MarketingAgencyPage /></Dash>} />
      <Route path="/dashboard/postings" element={<Dash><PostingsPage /></Dash>} />
      <Route path="/dashboard/calling" element={<Dash><AICallingPage /></Dash>} />
      <Route path="/dashboard/launchpad" element={<Dash><LaunchpadPage /></Dash>} />
      <Route path="/dashboard/reports" element={<Dash><ReportsPage /></Dash>} />
      <Route path="/dashboard/jobs" element={<Dash><JobsPage /></Dash>} />
      <Route path="/dashboard/blockchain" element={<Dash><BlockchainPage /></Dash>} />
      <Route path="/dashboard/agents/:agentType" element={<Dash><AgentDetailPage /></Dash>} />
      <Route path="/dashboard/account" element={<Dash><AccountPage /></Dash>} />
      <Route path="/dashboard/settings" element={<Dash><SettingsPage /></Dash>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
