import { ReportPage } from "@/components/research";

export default async function Page({ params }: { params: Promise<{ id: string; reportId: string }> }) {
  const { id, reportId } = await params;
  return <ReportPage projectId={id} reportId={reportId} />;
}
