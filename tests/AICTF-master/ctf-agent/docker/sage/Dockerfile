FROM sagemath/sagemath:latest

USER root

# Install Flask for the API wrapper
RUN sage -pip install flask gunicorn

# Copy the API wrapper to working directory
COPY sage_api.py /home/sage/sage_api.py
RUN chown sage:sage /home/sage/sage_api.py

# Expose the API port
EXPOSE 8617

# Run with gunicorn for production stability
USER sage
WORKDIR /home/sage

CMD ["sage", "-python", "-m", "gunicorn", "--bind", "0.0.0.0:8617", "--timeout", "300", "--workers", "2", "sage_api:app"]
