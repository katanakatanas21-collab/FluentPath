import CommunityPage from "./CommunityPage";

function AdminCommunityPage({ initialView = "posts" }) {
  return <CommunityPage role="administrator" initialView={initialView} />;
}

export default AdminCommunityPage;
