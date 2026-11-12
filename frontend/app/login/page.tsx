import { Login } from "@/components/login";

export default async function Page({ searchParams }: { searchParams: Promise<{ returnTo?: string }> }) {
  const { returnTo } = await searchParams;
  return <Login returnTo={returnTo} />;
}
