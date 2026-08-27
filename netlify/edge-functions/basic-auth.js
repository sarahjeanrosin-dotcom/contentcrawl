// Puts the whole dashboard behind HTTP Basic Auth. This exists because
// site/gated_data.json contains the full extracted text of gated
// whitepapers/eBooks -- without this, anyone with the URL could read the
// exact content that's supposed to require a lead-capture form, plus
// internal SharePoint folder paths and candid audit notes. Runs on every
// request (see the edge_functions block in netlify.toml), including the
// JSON/CSV data files, not just index.html.
//
// Credentials are read from Netlify environment variables at request time
// -- nothing is hardcoded here. Set DASHBOARD_USER and DASHBOARD_PASS in
// Netlify: Site settings -> Environment variables, then redeploy.
//
// Fails CLOSED: if either env var is missing, every request is blocked
// with a 500 rather than silently serving the site unprotected.

export default async (request, context) => {
  const user = Netlify.env.get("DASHBOARD_USER");
  const pass = Netlify.env.get("DASHBOARD_PASS");

  if (!user || !pass) {
    return new Response(
      "Dashboard auth is not configured -- set DASHBOARD_USER and DASHBOARD_PASS " +
      "in Netlify (Site settings > Environment variables) and redeploy.",
      { status: 500 }
    );
  }

  const expected = "Basic " + btoa(`${user}:${pass}`);
  const provided = request.headers.get("authorization");

  if (provided !== expected) {
    return new Response("Authentication required.", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="Genea Content Audit"' },
    });
  }

  return context.next();
};

export const config = { path: "/*" };
