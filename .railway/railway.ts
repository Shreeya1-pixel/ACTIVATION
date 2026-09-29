import { defineRailway, project, service } from "railway/iac";

// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "SIH_26";

export default defineRailway(() => {
  const SIH_26 = service("SIH_26", {
    healthcheck: "/api/health",
    healthcheckTimeout: 30,
    dockerfilePath: "deploy/Dockerfile.worker",
    builder: "DOCKERFILE",
  });
  return project("autostack-in", {
    resources: [SIH_26],
  });
});
