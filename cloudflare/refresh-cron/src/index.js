export default {
  async scheduled(event) {
    console.log(
      `ccass-refresh-cron disabled: received ${event?.cron || "manual"}; not dispatching GitHub Actions.`,
    );
  },
};
