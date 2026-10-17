FROM node:22-alpine

WORKDIR /app

# Install from the lockfile so the container gets the same dependency graph as
# local dev. `npm install` off package.json alone re-resolves the "latest" pins
# and can land on a mismatched vite/rolldown pair that fails to boot.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
