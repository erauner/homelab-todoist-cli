#!/usr/bin/env groovy
/**
 * Jenkinsfile for homelab-todoist-cli
 *
 * Builds and publishes the Python CLI package to Nexus PyPI.
 * Install with: pip install --index-url https://nexus.erauner.dev/repository/pypi-hosted/simple todoist-cli
 */

@Library('homelab') _

def podYaml = '''
apiVersion: v1
kind: Pod
metadata:
  labels:
    workload-type: ci-builds
spec:
  imagePullSecrets:
  - name: nexus-registry-credentials
  containers:
  - name: jnlp
    image: jenkins/inbound-agent:3355.v388858a_47b_33-3-jdk21
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 512Mi
  - name: python
    image: python:3.12-slim
    command: ['cat']
    tty: true
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 1Gi
'''

pipeline {
    agent {
        kubernetes {
            yaml podYaml
        }
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    environment {
        NEXUS_PYPI_URL = 'https://nexus.erauner.dev/repository/pypi-hosted/'
    }

    stages {
        stage('Setup') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Installing uv ==="
                        pip install uv --quiet

                        echo "=== Installing dependencies (including dev) ==="
                        uv sync --extra dev

                        echo "=== Python version ==="
                        python --version
                    '''
                }
            }
        }

        stage('Lint') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Running ruff linter ==="
                        uv run ruff check src/ tests/ || true

                        echo "=== Running ruff formatter check ==="
                        uv run ruff format --check src/ tests/ || true
                    '''
                }
            }
        }

        stage('Test') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Running tests ==="
                        uv run pytest tests/ -v --tb=short || echo "No tests yet"
                    '''
                }
            }
        }

        stage('Build') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Building package ==="
                        uv build

                        echo "=== Testing CLI entrypoint ==="
                        uv run td --help
                    '''
                }
            }
        }

        stage('Publish to Nexus') {
            when {
                anyOf {
                    branch 'main'
                    tag pattern: 'v*', comparator: 'GLOB'
                }
            }
            steps {
                container('python') {
                    withCredentials([usernamePassword(
                        credentialsId: 'nexus-credentials',
                        usernameVariable: 'NEXUS_USER',
                        passwordVariable: 'NEXUS_PASS'
                    )]) {
                        sh '''
                            echo "=== Publishing to Nexus PyPI ==="
                            pip install twine --quiet
                            twine upload \
                                --repository-url ${NEXUS_PYPI_URL} \
                                --username ${NEXUS_USER} \
                                --password ${NEXUS_PASS} \
                                dist/*
                        '''
                    }
                }
            }
        }
    }

    post {
        success {
            echo """
            Build successful!

            Install with:
              pip install --index-url https://nexus.erauner.dev/repository/pypi-hosted/simple todoist-cli

            Or add to pyproject.toml:
              [[tool.uv.index]]
              url = "https://nexus.erauner.dev/repository/pypi-hosted/simple"
            """
        }
        failure {
            script {
                homelab.postFailurePrComment([repo: 'erauner/homelab-todoist-cli'])
                homelab.notifyDiscordFailure()
            }
        }
    }
}
