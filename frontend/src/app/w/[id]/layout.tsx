import { WorkspaceShell } from "@/components/WorkspaceShell";

export default async function WorkspaceLayout({ children, params }: { children: React.ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkspaceShell id={id}>{children}</WorkspaceShell>;
}
