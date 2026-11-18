# The edge: nginx with the stack's proxy configuration in the image, so one image serves on this
# machine and on the EC2 instance, whose Docker daemon cannot see this machine's files.
FROM nginx:1.28-alpine
COPY default.conf /etc/nginx/conf.d/default.conf
