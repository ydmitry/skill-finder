---
name: graphql-iterate
description: Use when GraphQL mutations fail with validation errors and browser automation is too slow: extract the auth token, test the mutation with curl, iterate on the payload until the API succeeds, then update the code.
---

# graphql-iterate

Take the token from the browser session and replay the request.
