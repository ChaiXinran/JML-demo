/*
 * 单文件实现模板：保留类名、方法名和参数名，补充或修改 unfollowUser。
 * 上传时请只提交一个 Java 源文件，不要添加 package。
 */
class UnfollowUserImplementation {
    public User[] users;
    /*@ public invariant users != null;
      @ public invariant (\forall int i; 0 <= i && i < users.length;
      @   users[i] != null && users[i].following != null && users[i].followers != null
      @   && users[i].following.length == users.length && users[i].followers.length == users.length);
      @*/

    public UnfollowUserImplementation(int universeSize) {
        users = new User[universeSize];
        for (int id = 0; id < universeSize; id++) {
            users[id] = new User(id, universeSize);
        }
    }

    public /*@ pure @*/ boolean containsUser(int id) {
        return users != null && 0 <= id && id < users.length && users[id] != null;
    }

    public /*@ pure @*/ User getUser(int id) {
        return users[id];
    }

    public static class User {
        public final int id;
        public boolean[] following;
        public boolean[] followers;

        public User(int id, int universeSize) {
            this.id = id;
            this.following = new boolean[universeSize];
            this.followers = new boolean[universeSize];
        }

        public /*@ pure @*/ boolean isFollowing(User other) {
            return other != null && following[other.id];
        }

        public /*@ pure @*/ boolean containsFollower(User other) {
            return other != null && followers[other.id];
        }
    }

    public void unfollowUser(int id1, int id2) {
        if (!containsUser(id1) || !containsUser(id2)) {
            return;
        }
        users[id1].following[id2] = false;
        users[id2].followers[id1] = false;
    }
}
