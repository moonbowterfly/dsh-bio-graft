export function captureRoutes(registerIntegrationRoutes, service) {
  const routes = []
  const dispose = registerIntegrationRoutes({
    webServer: { register(route) { routes.push(route); return () => {} } },
  }, { service })
  return { routes, dispose }
}

export async function invokeRoute(route, {
  remoteAddress = '127.0.0.1', method = 'GET', headers = { host: 'localhost' },
} = {}) {
  let statusCode
  let body
  const req = { method, socket: { remoteAddress }, headers }
  const res = {
    writeHead(code) { statusCode = code },
    end(value) { body = JSON.parse(value) },
  }
  await route.handler(req, res)
  return { statusCode, body }
}
