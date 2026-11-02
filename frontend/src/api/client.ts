import createClient from "openapi-fetch";
import type { paths } from "./schema";

// Typed client generated from the backend OpenAPI schema (npm run gen:api).
export const api = createClient<paths>({ baseUrl: "", credentials: "include" });
