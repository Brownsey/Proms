import { notFound } from "next/navigation";

import ControlPanel from "./control-panel";
import { controlRouteAvailable } from "./environment";

export default function ControlPage() {
  if (!controlRouteAvailable(process.env.VERCEL)) notFound();
  return <ControlPanel />;
}
