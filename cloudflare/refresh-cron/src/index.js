export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchByCron(event, env));
  },
};

async function dispatchByCron(event, env) {
  const cron = event?.cron || "";
  const workflow = env.GITHUB_WORKFLOW || pickWorkflow(cron);
  return dispatchRefresh(env, workflow);
}

function pickWorkflow(cron) {
  if (cron === "30 23 * * 0-4") return "ccass_refresh.yml";
  return "ccass_refresh.yml";
}

async function dispatchRefresh(env, workflow) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const ref = env.GITHUB_REF || "main";
  const token = env.GITHUB_TOKEN;

  if (!owner || !repo) {
    throw new Error("Missing GITHUB_OWNER or GITHUB_REPO");
  }
  if (!token) {
    throw new Error("Missing GITHUB_TOKEN secret");
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${encodeURIComponent(workflow)}/dispatches`;
  const payload = {
    ref,
    inputs: {
      source: "cloudflare-cron",
    },
  };

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": "ccass-refresh-cron",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub workflow dispatch failed (${res.status}): ${text}`);
  }

  console.log(`Dispatched ${owner}/${repo} workflow ${workflow} on ${ref}`);
}
