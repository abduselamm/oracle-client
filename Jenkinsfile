pipeline {
    agent {
        node {
            label 'kr-jenkins-slave-1'
        }

    }

    

    environment {
        TELEGRAM_TOKEN = credentials('TELEGRAM_TOKEN')
        TELEGRAM_CHAT_ID = credentials('TELEGRAM_CHAT_ID')
        SERVICE_NAME = "oracle-client"
        FILE_PATH = "scripts/docker-compose.yml"
        DOCKER_FILE_PATH = "scripts/Dockerfile"
        ENV_FILE_PATH = "./env"
        HARBOR_PRODJECT = "cbe-superapp"
        REGISTRY_ADDRESS = credentials("REGISTRY_ADDRESS")
        REPO_ADDRESS = "https://github.com/abduselamm/oracle-client.git"
        PROJECT_ROOT_PATH = "/data/oracle-client/"
        SONAR_HOST_URL=credentials("SONAR_HOST_URL")
        SONAR_TOKEN=credentials("sonar-access-token")
        SONAR_SCANNER_HOME = tool 'SonarQube-Scanner'
        SHARED_GITHLAB_USER = credentials("SHARED_GITLAB_USER")
        SHARED_GITLAB_PAT = credentials("SHARED_GITLAB_PAT")

    }

    stages {
        // Initializing Env Variales
        stage('Initialize Environment') {
            steps {
                script {
                    // Set branch name fallback if not set
                    if (!env.BRANCH_NAME) {
                        if (env.GIT_BRANCH) {
                            env.BRANCH_NAME = env.GIT_BRANCH.tokenize('/').last()
                        } else {
                            error "BRANCH_NAME and GIT_BRANCH are not set!"
                        }
                    }
                    // Determine environment based on branch
                    if (env.BRANCH_NAME == 'main') {
                        env.ENV_TYPE = 'MAIN'
                        env.IMAGE_NAME = 'oracle-client-main'
                        env.SSH_KEY = 'MAIN_SSH_KEY'
                    }
                    else {
                        error "Unsupported branch: only main is permitted."
                    }
                    
                    // Load dynamic credentials using withCredentials after ENV_TYPE is set
                    withCredentials([
                        string(credentialsId: "REGISTRY_USER", variable: 'REGISTRY_USER'),
                        string(credentialsId: "REGISTRY_PASSWORD", variable: 'REGISTRY_PASSWORD'),
                    ]) {
                        env.REGISTRY_USER = env.REGISTRY_USER
                        env.REGISTRY_PASSWORD = env.REGISTRY_PASSWORD
                        echo "Building for environment: ${env.ENV_TYPE}"
                    }
                }
            }
        }
        // Stage to clone the Git repository
        stage('Cloning Git') {
            steps {
                checkout([
                    $class: 'GitSCM', 
                    branches: [[name: "*/${env.BRANCH_NAME}"]], 
                    doGenerateSubmoduleConfigurations: false, 
                    extensions: [], 
                    submoduleCfg: [], 
                    userRemoteConfigs: [[
                        credentialsId:  'GITHUB_CRED', 
                        url: env.REPO_ADDRESS
                    ]]
                ])  
            }
        }
        // Stage to set the commit SHA as the image tag
        stage('Set Commit SHA') {
            steps {
                script {
                    def sha = sh(script: "git rev-parse --short HEAD", returnStdout: true).trim() 
                    env.IMAGE_TAG = sha
                    echo "Image tag set to ${env.IMAGE_TAG}"
                }
            }
        }

        stage('Building Image and Define environmental variables') {
            steps {
                script {
                    docker.build("${env.IMAGE_NAME}:${env.IMAGE_TAG}", "-f ${env.DOCKER_FILE_PATH} --build-arg  GITLAB_USER=${env.SHARED_GITHLAB_USER} --build-arg  GITLAB_PAT=${env.SHARED_GITLAB_PAT}  .")
                }
            }
        }

        // Stage to push the image to the registry
        stage('Push Image to registry') {
            steps {
                script {
                    // Login to Docker registry
                    sh """
                        echo "Logging in to Docker registry at ${env.REGISTRY_ADDRESS}"
                        echo "${env.REGISTRY_PASSWORD}" | docker login ${env.REGISTRY_ADDRESS} -u "${env.REGISTRY_USER}" --password-stdin
                        docker image tag ${env.IMAGE_NAME}:${env.IMAGE_TAG} ${env.REGISTRY_ADDRESS}/${env.HARBOR_PRODJECT}/${env.IMAGE_NAME}:${env.IMAGE_TAG}
                        docker image tag ${env.IMAGE_NAME}:${env.IMAGE_TAG} ${env.REGISTRY_ADDRESS}/${env.HARBOR_PRODJECT}/${env.IMAGE_NAME}:latest
                        docker push ${env.REGISTRY_ADDRESS}/${env.HARBOR_PRODJECT}/${env.IMAGE_NAME}:${env.IMAGE_TAG}
                        docker push  ${env.REGISTRY_ADDRESS}/${env.HARBOR_PRODJECT}/${env.IMAGE_NAME}:latest
                        echo "Image pushed successfully to ${env.REGISTRY_ADDRESS}"
                        echo "Application deployed successfully to ${env.ENV_TYPE} server"
                        docker image rm  ${env.IMAGE_NAME}:${env.IMAGE_TAG}
                        docker image rm  ${env.REGISTRY_ADDRESS}/${env.HARBOR_PRODJECT}/${env.IMAGE_NAME}:${env.IMAGE_TAG}
                        docker image rm  ${env.REGISTRY_ADDRESS}/${env.HARBOR_PRODJECT}/${env.IMAGE_NAME}:latest
                    """
                }
            }
        }        
    }
    post {
        success {
            sh """
            curl -X POST \
            https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage \
            -d chat_id=${TELEGRAM_CHAT_ID}  \
            -d text="Build SUCCESS: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
            """
        }
        failure {
            sh """
            curl -X POST \
            https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage \
            -d chat_id=${TELEGRAM_CHAT_ID}  \
            -d text="Build FAILED: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
            """
        }
    }
}