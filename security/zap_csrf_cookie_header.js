function sendingRequest(message, initiator, helper) {
    var uri = message.getRequestHeader().getURI();
    if (String(uri.getScheme()) !== "https" || String(uri.getHost()) !== "pfis.test") {
        return;
    }

    var cookieHeader = message.getRequestHeader().getHeader("Cookie");
    if (cookieHeader === null) {
        return;
    }

    var prefix = "__Host-pfis-csrf=";
    var cookies = String(cookieHeader).split(";");
    for (var index = 0; index < cookies.length; index += 1) {
        var cookie = cookies[index].trim();
        if (cookie.indexOf(prefix) !== 0) {
            continue;
        }
        var token = cookie.substring(prefix.length);
        if (token.length > 0 && !/[\r\n;]/.test(token)) {
            message.getRequestHeader().setHeader("X-CSRF-Token", token);
        }
        return;
    }
}

function responseReceived(message, initiator, helper) {}
