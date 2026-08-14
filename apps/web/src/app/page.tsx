import { redirect } from "next/navigation";

/** The root has no content of its own; the shell's guard handles the rest. */
export default function RootPage() {
  redirect("/dashboard");
}
