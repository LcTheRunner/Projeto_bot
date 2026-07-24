const localtunnel = require('localtunnel');

async function start() {
  try {
    const tunnel = await localtunnel({
      port: 4200,
      local_host: 'host.docker.internal',
      subdomain: process.env.TUNNEL_SUBDOMAIN
    });
    console.log(`PUBLIC_URL=${tunnel.url}`, { flush: true });
    tunnel.on('error', error => console.error('TUNNEL_ERROR', error));
    tunnel.on('close', () => console.error('TUNNEL_CLOSED'));
  } catch (error) {
    console.error('TUNNEL_START_ERROR', error);
    process.exit(1);
  }
}

start();
