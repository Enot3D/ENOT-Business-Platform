import { Suspense } from "react";
import { Catalog } from "@/components/catalog";
import { Loading } from "@/components/states";

export default function Page() {
  return <Suspense fallback={<Loading />}><Catalog /></Suspense>;
}
